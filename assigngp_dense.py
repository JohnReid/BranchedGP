# coding: utf-8

import GPflow
import numpy as np
import tensorflow as tf
import pZ_construction_singleBP
from matplotlib import pyplot as plt

# TODO S:
# 1) create a parameter for breakpoints (in the kernel perhaps?) - done
# 2) tidy up make_pZ_matrix and generalize to multiple latent functions


def PlotSample(D, X, M, samples, B=None, lw=3.,
               fs=10, figsizeIn=(12, 16), title=None, mV=None):
    f, ax = plt.subplots(D, 1, figsize=figsizeIn, sharex=True, sharey=True)
    nb = len(B)  # number of branch points
    for d in range(D):
        for i in range(1, M+1):
            t = X[X[:, 1] == i, 0]
            y = samples[X[:, 1] == i, d]
            if(t.size == 0):
                continue
            if(D != 1):
                p = ax.flatten()[d]
            else:
                p = ax

            p.plot(t, y, '.', label=i, markersize=2*lw)
            p.text(t[t.size/2], y[t.size/2], str(i), fontsize=fs)
        # Add vertical lines for branch points
        if(title is not None):
            p.set_title(title + ' Dim=' + str(d), fontsize=fs)

        if(B is not None):
            v = p.axis()
            for i in range(nb):
                p.plot([B[i], B[i]], v[-2:], '--r')
        if(mV is not None):
            assert B.size == 1, 'Code limited to one branch point, got ' + str(B.shape)
            print 'plotting mv'
            pt = mV.t
            l = np.min(pt)
            u = np.max(pt)
            for f in range(1, 4):
                if(f == 1):
                    ttest = np.linspace(l, B.flatten(), 100)[:, None]  # root
                else:
                    ttest = np.linspace(B.flatten(), u, 100)[:, None]
                Xtest = np.hstack((ttest, ttest*0+f))
                mu, var = mV.predict_f(Xtest)
                assert np.all(np.isfinite(mu)), 'All elements should be finite but are ' + str(mu)
                assert np.all(np.isfinite(var)), 'All elements should be finite but are ' + str(var)
                mean, = p.plot(ttest, mu[:, d], linewidth=lw)
                col = mean.get_color()
                # print 'd='+str(d)+ ' f='+str(f) + '================'
                # variance is common for all outputs!
                p.plot(ttest.flatten(), mu[:, d] + 2*np.sqrt(var.flatten()), '--', color=col, linewidth=lw)
                p.plot(ttest, mu[:, d] - 2*np.sqrt(var.flatten()), '--', color=col, linewidth=lw)

    plt.legend(bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0.)

# PlotSample(D, m.XExpanded[bestAssignment, : ], 3, Y, Bcrap, lw=5., fs=30, mV=mV, figsizeIn=(D*10, D*7), title='Posterior B=%.1f -loglik= %.2f VB= %.2f'%(b, -chainState[-1], VBbound))


def plotPosterior(pt, Bv, mV, figsizeIn=(12, 16)):
    l = np.min(pt)
    u = np.max(pt)
    D = mV.Y.shape
    f, ax = plt.subplots(D, 1, figsize=figsizeIn, sharex=True, sharey=True)

    for f in range(1, 4):
        # fig = plt.figure(figsize=(12, 8))
        if(f == 1):
            ttest = np.linspace(l, Bv, 100)[:, None]  # root
        else:
            ttest = np.linspace(Bv, u, 100)[:, None]
        Xtest = np.hstack((ttest, ttest*0+f))
        mu, var = mV.predict_f(Xtest)
        assert np.all(np.isfinite(mu)), 'All elements should be finite but are ' + str(mu)
        assert np.all(np.isfinite(var)), 'All elements should be finite but are ' + str(var)
        mean, = plt.plot(ttest, mu)
        col = mean.get_color()
        plt.plot(ttest, mu + 2*np.sqrt(var), '--', color=col)
        plt.plot(ttest, mu - 2*np.sqrt(var), '--', color=col)


class AssignGP(GPflow.model.GPModel):
    """
    Gaussian Process regression, but where the index to which the data are
    assigned is unknown.

    let f be a vector of GP points (usually longer than the number of data)

        f ~ MVN(0, K)

    and let Z be an (unknown) binary matrix with a single 1 in each row. The
    likelihood is

       y ~ MVN( Z f, \sigma^2 I)

    That is, each element of y is a noisy realization of one (unknown) element
    of f. We use variational Bayes to infer the labels using a sparse prior
    over the Z matrix (i.e. we have narrowed down the choice of which function
    values each y is drawn from).

    """
    def __init__(self, t, XExpanded, Y, kern, ZExpanded=None):
        GPflow.model.GPModel.__init__(self, XExpanded, Y, kern,
                                      likelihood=GPflow.likelihoods.Gaussian(),
                                      mean_function=GPflow.mean_functions.Zero())
        self.logPhi = GPflow.param.Param(np.random.randn(t.shape[0], t.shape[0] * 3))

        self.t = t
        
        self.ZExpanded = ZExpanded  # inducing poitns for sparse GP, optional. Same format as XExpanded
        
        assert self.kern.branchkernelparam.Bv.fixed, 'Branching value should be fixed.'
        
    def GetPhi(self):
        ''' Shortcut function to get Phi matrix out. '''
        with self.tf_mode():
            Phi_s = tf.nn.softmax(self.logPhi)
        Phi = self._session.run(Phi_s, feed_dict={self._free_vars: self.get_free_state()})

        return Phi

    def InitialisePhi(self, indices, bestAssignment, Bv, fSoftAssignment=False):
        ''' Convert MAP assignments to Phi probabilities : soft or hard assignment
        Soft assignment uses the Gibbs conditional probabilities at convergence
        Hard assignment uses the MAP assignment setting Phi to 1 for that entry.
        Initialises self.logPhi. Return phiInitial'''
        N = len(bestAssignment)
        if(fSoftAssignment):
            phiInitial = np.zeros((N, 3*N))
            phiInitial_invSoftmax = -9. * np.ones((N, 3*N))  # large neg number makes exact zeros, make smaller for added jitter
            ct = 1
            for i, n in reversed(list(enumerate(bestAssignment))):
                # print '----------->' + str(i) + ','+str(n)
                if(self.t[i] > Bv):
                    # after branch point - we look at assignment probabilities
                    ind = indices[i][1:]  # single branching point special case - just take second and third indics
                    for indxi in ind:
                        if(indxi == bestAssignment[i]):
                            phiInitial[i, indxi] = 0.9 # 0.999
                        else:
                            phiInitial[i, indxi] = 0.1 # 0.001
                        phiInitial_invSoftmax[i, indxi] = np.log(phiInitial[i, indxi])
                    ct += 1
                else:
                    # before branch point - we know with certainty
                    phiInitial[i, n] = 1
                    phiInitial_invSoftmax[i, n] = 1  # 10
                    # print str(i) + ' ' + str(n) + '=' + str(mCond[p])
        else:
            # hard assignment
            # Set state for assignments
            phiInitial = np.zeros((N, 3*N))
            phiInitial_invSoftmax = np.zeros((N, 3*N))  # large neg number makes exact zeros, make smaller for added jitter
            for i, n in enumerate(bestAssignment):
                phiInitial[i, n] = 1
                phiInitial_invSoftmax[i, n] = 10

        self.logPhi = phiInitial_invSoftmax
        return phiInitial

    def build_likelihood(self):
        if self.ZExpanded is None:
            return self.build_likelihood_full()
        else:
            return self.build_likelihood_sparse()

    def build_likelihood_sparse(self):
        N = self.Y.shape[0]*1.0
        M = self.ZExpanded.shape[0]
        
        with tf.name_scope('prepare1'):
            Phi = tf.nn.softmax(self.logPhi)
            # try squashing Phi to avoid numerical errors
            Phi = (1-2e-6) * Phi + 1e-6

            tau = 1./self.likelihood.variance
        with tf.name_scope('prepare3'):
            Kuu = self.kern.K(self.ZExpanded) + GPflow.tf_hacks.eye(M) * 1e-6
        with tf.name_scope('prepare4'):
            Kuf = self.kern.K(self.ZExpanded, self.X)
        with tf.name_scope('prepare5'):
            Kdiag = self.kern.Kdiag(self.X)
        with tf.name_scope('prepare6'):
            L = tf.cholesky(Kuu)
        with tf.name_scope('prepare7'):
            W = tf.matrix_triangular_solve(L, Kuf)

        with tf.name_scope('prepare8'):
            p = tf.reduce_sum(Phi, 0)
        with tf.name_scope('prepare9'):
            LTA = W * tf.sqrt(p)

        with tf.name_scope('prepare10'):
            P = tf.matmul(LTA, tf.transpose(LTA)) * tau + GPflow.tf_hacks.eye(M)

        with tf.name_scope('prepare11'):
            traceTerm = -0.5 * tau * (tf.reduce_sum(Kdiag*p) - tf.reduce_sum(tf.square(LTA)))

        with tf.name_scope('prepare12'):
            R = tf.cholesky(P)
        with tf.name_scope('prepare13'):
            PhiY = tf.matmul(Kuf, tf.matmul(tf.transpose(Phi), self.Y))
        with tf.name_scope('prepare14'):
            LPhiY = tf.matmul(tf.transpose(L), PhiY)
        with tf.name_scope('prepare15'):
            RiLPhiY = tf.matrix_triangular_solve(R, LPhiY, lower=True)
    
        D = self.Y.shape[1]
        with tf.name_scope('prepare16'):
            KL = self.build_KL(Phi)
        with tf.name_scope('prepare21'):
            self.bound = traceTerm + 0.5*N*D*tf.log(tau)\
                - 0.5*D*tf.reduce_sum(tf.log(tf.square(tf.diag_part(R))))\
                - 0.5*tau*tf.reduce_sum(tf.square(self.Y))\
                + 0.5*tf.reduce_sum(tf.square(tau * RiLPhiY))
        with tf.name_scope('prepare22'):
            self.bound = self.bound - KL
        
        return self.bound

    def build_likelihood_full(self):
        N = self.Y.shape[0]
        M = self.X.shape[0]

        K = self.kern.K(self.X)
        Phi = tf.nn.softmax(self.logPhi)

        # try sqaushing Phi to avoid numerical errors
        Phi = (1-2e-6) * Phi + 1e-6

        # Phi = tf.Print(Phi, [tf.shape(Phi), Phi], message='Phi=', name='Phidebug', summarize=10) # will print message
        tau = 1./self.likelihood.variance

        L = tf.cholesky(K) + GPflow.tf_hacks.eye(M)*1e-6
        LTA = tf.transpose(L) * tf.sqrt(tf.reduce_sum(Phi, 0))
        P = tf.matmul(LTA, tf.transpose(LTA)) * tau + GPflow.tf_hacks.eye(M)
        R = tf.cholesky(P)

        PhiY = tf.matmul(tf.transpose(Phi), self.Y)
        LPhiY = tf.matmul(tf.transpose(L), PhiY)
        RiLPhiY = tf.matrix_triangular_solve(R, LPhiY, lower=True)

        # compute KL
        KL = self.build_KL(Phi)

        D = self.Y.shape[1]
        return -0.5*N*D*tf.log(2*np.pi/tau)\
            - 0.5*D*tf.reduce_sum(tf.log(tf.square(tf.diag_part(R))))\
            - 0.5*tau*tf.reduce_sum(tf.square(self.Y))\
            + 0.5*tf.reduce_sum(tf.square(tau * RiLPhiY)) - KL

    def build_KL(self, Phi):
        Bv_s = tf.squeeze(self.kern.branchkernelparam.Bv, squeeze_dims=[1])
        pZ = pZ_construction_singleBP.make_matrix(self.t, Bv_s)  # breakpoints stored in kernel whose location is hardcoded
        return tf.reduce_sum(Phi * tf.log(Phi)) - tf.reduce_sum(Phi * tf.log(pZ))

    def build_predict(self, Xnew):
        if self.ZExpanded is None:
            return self.build_predict_full(Xnew)
        else:
            return self.build_predict_sparse(Xnew)
        
    def build_predict_full(self, Xnew):
        M = self.X.shape[0]

        K = self.kern.K(self.X)
        L = tf.cholesky(K)
        tmp = tf.matrix_triangular_solve(L, GPflow.tf_hacks.eye(M), lower=True)
        Ki = tf.matrix_triangular_solve(tf.transpose(L), tmp, lower=False)
        tau = 1./self.likelihood.variance

        Phi = tf.nn.softmax(self.logPhi)

        # try sqaushing Phi to avoid numerical errors
        Phi = (1-2e-6) * Phi + 1e-6

        A = tf.diag(tf.reduce_sum(Phi, 0))

        Lamb = A * tau + Ki  # posterior precision
        R = tf.cholesky(Lamb)
        PhiY = tf.matmul(tf.transpose(Phi), self.Y)
        tmp = tf.matrix_triangular_solve(R, PhiY, lower=True) * tau
        mean_f = tf.matrix_triangular_solve(tf.transpose(R), tmp, lower=False)

        # project onto Xnew
        Kfx = self.kern.K(self.X, Xnew)
        Kxx = self.kern.Kdiag(Xnew)

        A = tf.matrix_triangular_solve(L, Kfx, lower=True)
        B = tf.matrix_triangular_solve(tf.transpose(L), A, lower=False)

        mean = tf.matmul(tf.transpose(B), mean_f)
        var = Kxx - tf.reduce_sum(tf.square(A), 0)
        RiB = tf.matrix_triangular_solve(R, B, lower=True)
        var = var + tf.reduce_sum(RiB, 0)

        return mean, tf.expand_dims(var, 1)
    
    def build_predict_sparse(self, Xnew):
        # Not modified to use sparse representation! UNDONE
        
        # Predict code            
        M = self.X.shape[0]

        K = self.kern.K(self.X)
        L = tf.cholesky(K)
        tmp = tf.matrix_triangular_solve(L, GPflow.tf_hacks.eye(M), lower=True)
        Ki = tf.matrix_triangular_solve(tf.transpose(L), tmp, lower=False)
        tau = 1./self.likelihood.variance

        Phi = tf.nn.softmax(self.logPhi)

        # try sqaushing Phi to avoid numerical errors
        Phi = (1-2e-6) * Phi + 1e-6

        A = tf.diag(tf.reduce_sum(Phi, 0))

        Lamb = A * tau + Ki  # posterior precision
        R = tf.cholesky(Lamb)
        PhiY = tf.matmul(tf.transpose(Phi), self.Y)
        tmp = tf.matrix_triangular_solve(R, PhiY, lower=True) * tau
        mean_f = tf.matrix_triangular_solve(tf.transpose(R), tmp, lower=False)

        # project onto Xnew
        Kfx = self.kern.K(self.X, Xnew)
        Kxx = self.kern.Kdiag(Xnew)

        A = tf.matrix_triangular_solve(L, Kfx, lower=True)
        B = tf.matrix_triangular_solve(tf.transpose(L), A, lower=False)

        mean = tf.matmul(tf.transpose(B), mean_f)
        var = Kxx - tf.reduce_sum(tf.square(A), 0)
        RiB = tf.matrix_triangular_solve(R, B, lower=True)
        var = var + tf.reduce_sum(RiB, 0)

        return mean, tf.expand_dims(var, 1)    
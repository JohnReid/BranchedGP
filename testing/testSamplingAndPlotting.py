import pandas as pd
import numpy as np
import pickle
from matplotlib import pyplot as plt
import GPflow
from BranchedGP import VBHelperFunctions as bplot
from BranchedGP import BranchingTree as bt
from BranchedGP import branch_kernParamGPflow as bk
import unittest
from BranchedGP import FitBranchingModel

class TestSamplingAndPlotting(unittest.TestCase):
    def test(self):
        branchingPoint = 0.5
        tree = bt.BinaryBranchingTree(0, 10, fDebug=False)  # set to true to print debug messages
        tree.add(None, 1, branchingPoint)  # single branching point
        (fm, fmb) = tree.GetFunctionBranchTensor()
        # Specify where to evaluate the kernel
        t = np.linspace(0.01, 1, 100)
        (XForKernel, indicesBranch, Xtrue) = tree.GetFunctionIndexList(t, fReturnXtrue=True)
        # Specify the kernel and its hyperparameters
        # These determine how smooth and variable the branching functions are
        Bvalues = np.expand_dims(np.asarray(tree.GetBranchValues()), 1)
        KbranchParam = bk.BranchKernelParam(GPflow.kernels.RBF(1), fm, b=Bvalues)
        KbranchParam.kern.lengthscales = 2
        KbranchParam.kern.variance = 1
        # Sample the kernel
        samples = bk.SampleKernel(KbranchParam, XForKernel)
        # Plot the sample
        bk.PlotSample(XForKernel, samples)
        # Fit model
        BgridSearch = [0.1, branchingPoint, 1.1]
        globalBranchingLabels = XForKernel[:, 1]  # use correct labels for tests
        # could add a mistake
        d = FitBranchingModel.FitModel(BgridSearch, XForKernel[:, 0], samples, globalBranchingLabels,
                                       maxiter=20, priorConfidence=0.80)

        # Plot model
        bmode = BgridSearch[np.argmax(d['loglik'])]
        assert bmode == branchingPoint, bmode
        pred = d['prediction']  # prediction object from GP
        _=bplot.plotBranchModel(bmode, XForKernel[:, 0], samples, pred['xtest'], pred['mu'], pred['var'],
                                d['Phi'], fPlotPhi=True, fColorBar=True, fPlotVar = True)


        _=bplot.PlotBGPFit(samples, XForKernel[:, 0], BgridSearch, d)

        # You can rerun the same code as many times as you want and get different sample paths
        # We can also sample independent functions. This is the assumption in the overlapping mixtures of GPs model (OMGP) discussed in the paper.
        indKernel = bk.IndKern(GPflow.kernels.RBF(1))
        samplesInd = bk.SampleKernel(indKernel, XForKernel)

if __name__ == '__main__':
    unittest.main()


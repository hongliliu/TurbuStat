# Licensed under an MIT open source license - see LICENSE

'''
Test functions for PCA
'''

from unittest import TestCase
import pytest

import numpy as np
import numpy.testing as npt

from ..statistics import PCA, PCA_Distance
from ..statistics.pca.width_estimate import WidthEstimate1D, WidthEstimate2D
from ._testing_data import (dataset1, dataset2, computed_data,
                            computed_distances, generate_2D_array,
                            generate_1D_array)


class testPCA(TestCase):

    def setUp(self):
        self.dataset1 = dataset1
        self.dataset2 = dataset2

    def test_PCA_method(self):
        self.tester = PCA(dataset1["cube"], n_eigs=50)
        self.tester.run(mean_sub=True)
        npt.assert_allclose(self.tester.eigvals, computed_data['pca_val'])

    def test_PCA_distance(self):
        self.tester_dist = \
            PCA_Distance(dataset1["cube"],
                         dataset2["cube"]).distance_metric()
        npt.assert_almost_equal(self.tester_dist.distance,
                                computed_distances['pca_distance'])


@pytest.mark.parameterize(('method'), ('fit', 'contour', 'interpolate',
                                       'xinterpolate'))
def test_spatial_width_methods(method):
    '''
    Generate a 2D gaussian and test whether each method returns the expected
    size.
    '''

    model_gauss = generate_2D_array(x_std=10, y_std=10)

    model_gauss = model_gauss[np.newaxis, :]

    widths = WidthEstimate2D(model_gauss, method=method)

    npt.assert_approx_equal(widths[0], 10.0, significant=3)


@pytest.mark.parameterize(('method'), ('fit', 'interpolate'))
def test_spectral_width_methods(method):
    '''
    Generate a 1D gaussian and test whether each method returns the expected
    size.
    '''

    model_gauss = generate_1D_array(std=10)
    model_gauss = model_gauss[model_gauss != 0.0]

    model_gauss = model_gauss[:, np.newaxis]

    widths = WidthEstimate1D(model_gauss, method=method)

    npt.assert_approx_equal(10.0, widths[0], significant=3)

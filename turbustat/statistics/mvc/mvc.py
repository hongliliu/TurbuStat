# Licensed under an MIT open source license - see LICENSE
from __future__ import print_function, absolute_import, division

import numpy as np
from numpy.fft import fft2, fftshift
import astropy.units as u
from warnings import warn

from ..base_pspec2 import StatisticBase_PSpec2D
from ..base_statistic import BaseStatisticMixIn
from ...io import input_data, common_types, twod_types
from ..fitting_utils import check_fit_limits


class MVC(BaseStatisticMixIn, StatisticBase_PSpec2D):

    """
    Implementation of Modified Velocity Centroids (Lazarian & Esquivel, 03)

    Parameters
    ----------
    centroid : %(dtypes)s
        Normalized first moment array.
    moment0 : %(dtypes)s
        Moment 0 array.
    linewidth : %(dtypes)s
        Normalized second moment array
    header : FITS header
        Header of any of the arrays. Used only to get the
        spatial scale.
    distance : `~astropy.units.Quantity`, optional
        Physical distance to the region in the data.
    """

    __doc__ %= {"dtypes": " or ".join(common_types + twod_types)}

    def __init__(self, centroid, moment0, linewidth, header=None,
                 distance=None):

        # data property not used here
        self.no_data_flag = True
        self.data = None

        if header is None:
            try:
                self._centroid, self.header = input_data(centroid,
                                                         no_header=False)
            except TypeError:
                warn("Could not load header from centroid. No header has been"
                     " specified.")
                self._centroid = input_data(centroid, no_header=True)

        else:
            self._centroid = input_data(centroid, no_header=True)
            self.header = header

        if distance is not None:
            self.distance = distance

        self._moment0 = input_data(moment0, no_header=True)
        self._linewidth = input_data(linewidth, no_header=True)

        # Get rid of nans.
        self._centroid[np.isnan(self.centroid)] = np.nanmin(self.centroid)
        self._moment0[np.isnan(self.moment0)] = np.nanmin(self.moment0)
        self._linewidth[np.isnan(self.linewidth)] = np.nanmin(self.linewidth)

        shape_check1 = self.centroid.shape == self.moment0.shape
        shape_check2 = self.centroid.shape == self.linewidth.shape
        if not shape_check1 or not shape_check2:
            raise IndexError("The centroid, moment0, and linewidth arrays must"
                             "have the same shape.")

        self.shape = self.centroid.shape

        self._ps1D_stddev = None

    @property
    def centroid(self):
        '''
        Normalized centroid array.
        '''
        return self._centroid

    @property
    def moment0(self):
        '''
        Zeroth moment (integrated intensity) array.
        '''
        return self._moment0

    @property
    def linewidth(self):
        '''
        Linewidth array. Square root of the velocity dispersion.
        '''
        return self._linewidth

    def compute_pspec(self):
        '''
        Compute the 2D power spectrum.

        The quantity calculated here is the same as Equation 3 in Lazarian &
        Esquivel (2003), but the inputted arrays are not in the same form as
        described. We can, however, adjust for the use of normalized Centroids
        and the linewidth.

        An unnormalized centroid can be constructed by multiplying the centroid
        array by the moment0. Velocity dispersion is the square of the
        linewidth subtracted by the square of the normalized centroid.
        '''

        term1 = fft2(self.centroid * self.moment0)

        # Account for normalization in the line width.
        term2 = np.nanmean(self.linewidth**2 + self.centroid**2)

        mvc_fft = term1 - term2 * fft2(self.moment0)

        # Shift to the center
        mvc_fft = fftshift(mvc_fft)

        self._ps2D = np.abs(mvc_fft) ** 2.

    def run(self, verbose=False, save_name=None, logspacing=False,
            return_stddev=True, low_cut=None, high_cut=None,
            fit_2D=True, fit_2D_kwargs={},
            xunit=u.pix**-1, use_wavenumber=False, **fit_kwargs):
        '''
        Full computation of MVC. For fitting parameters and radial binning
        options, see `~turbustat.statistics.base_pspec2.StatisticBase_PSpec2D`.

        Parameters
        ----------
        verbose: bool, optional
            Enables plotting.
        save_name : str,optional
            Save the figure when a file name is given.
        logspacing : bool, optional
            Return logarithmically spaced bins for the lags.
        return_stddev : bool, optional
            Return the standard deviation in the 1D bins.
        low_cut : `~astropy.units.Quantity`, optional
            Low frequency cut off in frequencies used in the fitting.
        high_cut : `~astropy.units.Quantity`, optional
            High frequency cut off in frequencies used in the fitting.
        fit_2D : bool, optional
            Fit an elliptical power-law model to the 2D power spectrum.
        fit_2D_kwargs : dict, optional
            Keyword arguments for `MVC.fit_2Dpspec`. Use the
            `low_cut` and `high_cut` keywords to provide fit limits.
        xunit : u.Unit, optional
            Choose the angular unit to convert to when ang_units is enabled.
        use_wavenumber : bool, optional
            Plot the x-axis as the wavenumber rather than spatial frequency.
        fit_kwargs : Passed to `~MVC.fit_pspec`.
        '''

        self.compute_pspec()
        self.compute_radial_pspec(logspacing=logspacing,
                                  return_stddev=return_stddev)
        self.fit_pspec(low_cut=low_cut, high_cut=high_cut, **fit_kwargs)

        if fit_2D:
            self.fit_2Dpspec(low_cut=low_cut, high_cut=high_cut,
                             **fit_2D_kwargs)

        if verbose:
            print(self.fit.summary())

            self.plot_fit(show=True, show_2D=True,
                          xunit=xunit, save_name=save_name,
                          use_wavenumber=use_wavenumber)
            if save_name is not None:
                import matplotlib.pyplot as p
                p.close()

        return self


class MVC_Distance(object):
    """
    Distance metric for MVC.

    Parameters
    ----------
    data1 : dict
        A dictionary containing the centroid, moment 0, and linewidth arrays
        of a spectral cube. This output is created by Mask_and_Moments.to_dict.
        The minimum expected keys are 'centroid', 'moment0' and 'linewidth'. If
        weight_by_error is enabled, the dictionary should also contain the
        error arrays, where the keys are the three above with '_error'
        appended to the end.
    data2 : dict
        See data1.
    fiducial_model : MVC
        Computed MVC object. use to avoid recomputing.
    weight_by_error : bool, optional
        When enabled, the property arrays are weighted by the inverse
        squared of the error arrays.
    low_cut : `~astropy.units.Quantity` or np.ndarray, optional
        The lower frequency fitting limit. An array with 2 elements can be
        passed to give separate lower limits for the datasets.
    high_cut : `~astropy.units.Quantity` or np.ndarray, optional
        The upper frequency fitting limit. See `low_cut` above. Defaults to
        0.5.
    breaks : `~astropy.units.Quantity`, list or array, optional
        Specify where the break point is with appropriate units.
        If none is given, no break point will be used in the fit.
    logspacing : bool, optional
        Use logarithmically spaced bins in the 1D power spectrum.
    phys_distance : `~astropy.units.Quantity`, optional
        Physical distance to the region in the data.
    """

    def __init__(self, data1, data2, fiducial_model=None,
                 weight_by_error=False, low_cut=None, high_cut=0.5 / u.pix,
                 breaks=None, logspacing=False, phys_distance=None):

        # Create weighted or non-weighted versions
        if weight_by_error:
            centroid1 = data1["centroid"][0] * \
                data1["centroid_error"][0] ** -2.
            moment01 = data1["moment0"][0] * \
                data1["moment0_error"][0] ** -2.
            linewidth1 = data1["linewidth"][0] * \
                data1["linewidth_error"][0] ** -2.
            centroid2 = data2["centroid"][0] * \
                data2["centroid_error"][0] ** -2.
            moment02 = data2["moment0"][0] * \
                data2["moment0_error"][0] ** -2.
            linewidth2 = data2["linewidth"][0] * \
                data2["linewidth_error"][0] ** -2.
        else:
            centroid1 = data1["centroid"][0]
            moment01 = data1["moment0"][0]
            linewidth1 = data1["linewidth"][0]
            centroid2 = data2["centroid"][0]
            moment02 = data2["moment0"][0]
            linewidth2 = data2["linewidth"][0]

        low_cut, high_cut = check_fit_limits(low_cut, high_cut)

        if not isinstance(breaks, list) and not isinstance(breaks, np.ndarray):
            breaks = [breaks] * 2

        if fiducial_model is not None:
            self.mvc1 = fiducial_model
        else:
            self.mvc1 = MVC(centroid1, moment01, linewidth1,
                            data1["centroid"][1], distance=phys_distance)
            self.mvc1.run(logspacing=logspacing, high_cut=high_cut[0],
                          low_cut=low_cut[0], brk=breaks[0], fit_2D=False)

        self.mvc2 = MVC(centroid2, moment02, linewidth2,
                        data2["centroid"][1], distance=phys_distance)
        self.mvc2.run(logspacing=logspacing, high_cut=high_cut[1],
                      low_cut=low_cut[1], brk=breaks[1], fit_2D=False)

    def distance_metric(self, verbose=False, label1=None, label2=None,
                        xunit=u.pix**-1, save_name=None,
                        use_wavenumber=False):
        '''

        Implements the distance metric for 2 MVC transforms.
        We fit the linear portion of the transform to represent the powerlaw
        A linear model with an interaction term is fit to the two powerlaws.
        The distance is the t-statistic of the interaction.

        Parameters
        ----------
        verbose : bool, optional
            Enables plotting.
        label1 : str, optional
            Object or region name for dataset1
        label2 : str, optional
            Object or region name for dataset2
        ang_units : bool, optional
            Convert frequencies to angular units using the given header.
        xunit : u.Unit, optional
            Choose the unit to convert the x-axis to in the plot.
        save_name : str,optional
            Save the figure when a file name is given.
        use_wavenumber : bool, optional
            Plot the x-axis as the wavenumber rather than spatial frequency.
        '''

        # Construct t-statistic
        self.distance = \
            np.abs((self.mvc1.slope - self.mvc2.slope) /
                   np.sqrt(self.mvc1.slope_err**2 +
                           self.mvc2.slope_err**2))

        if verbose:
            print(self.mvc1.fit.summary())
            print(self.mvc2.fit.summary())

            import matplotlib.pyplot as p

            self.mvc1.plot_fit(show=False, color='b', label=label1, symbol='D',
                               xunit=xunit,
                               use_wavenumber=use_wavenumber)
            self.mvc2.plot_fit(show=False, color='g', label=label2, symbol='o',
                               xunit=xunit,
                               use_wavenumber=use_wavenumber)
            p.legend(loc='best')

            if save_name is not None:
                p.savefig(save_name)
                p.close()
            else:
                p.show()

        return self

# Licensed under an MIT open source license - see LICENSE
from __future__ import print_function, absolute_import, division

import numpy as np
from scipy.stats import binned_statistic


def pspec(psd2, nbins=None, return_stddev=False, binsize=1.0,
          logspacing=True, max_bin=None, min_bin=None, return_freqs=True):
    '''
    Calculate the radial profile using scipy.stats.binned_statistic.

    Parameters
    ----------
    psd2 : np.ndarray
        2D Spectral power density.
    nbins : int, optional
        Number of bins to use. If None, it is calculated based on the size
        of the given arrays.
    return_stddev : bool, optional
        Return the standard deviations in each bin.
    binsize : float, optional
        Size of bins to be used. If logspacing is enabled, this will increase
        the number of bins used by the inverse of the given binsize.
    logspacing : bool, optional
        Use logarithmically spaces bins.
    max_bin : float, optional
        Give the maximum value to bin to.
    min_bin : float, optional
        Give the minimum value to bin to.
    return_freqs : bool, optional
        Return spatial frequencies.

    Returns
    -------
    bins_cents : np.ndarray
        Centre of the bins.
    ps1D : np.ndarray
        1D binned power spectrum.
    ps1D_stddev : np.ndarray
        Returned when return_stddev is enabled. Standard deviations
        within each of the bins.
    '''

    yy, xx = make_radial_arrays(psd2.shape)

    dists = np.sqrt(yy**2 + xx**2)

    if nbins is None:
        nbins = int(np.round(dists.max() / binsize) + 1)

    if return_freqs:
        yy_freq, xx_freq = make_radial_freq_arrays(psd2.shape)

        freqs_dist = np.sqrt(yy_freq**2 + xx_freq**2)

        zero_freq_val = freqs_dist[np.nonzero(freqs_dist)].min() / 2.
        freqs_dist[freqs_dist == 0] = zero_freq_val

    if max_bin is None:
        if return_freqs:
            max_bin = 0.5
        else:
            max_bin = dists.max()

    if min_bin is None:
        if return_freqs:
            min_bin = 1.0 / min(psd2.shape)
        else:
            min_bin = 0.5

    if logspacing:
        bins = np.logspace(np.log10(min_bin), np.log10(max_bin), nbins + 1)
    else:
        bins = np.linspace(min_bin, max_bin, nbins + 1)

    if return_freqs:
        dist_arr = freqs_dist
    else:
        dist_arr = dists

    ps1D, bin_edge, cts = binned_statistic(dist_arr.ravel(),
                                           psd2.ravel(),
                                           bins=bins,
                                           statistic=np.nanmean)

    bin_cents = (bin_edge[1:] + bin_edge[:-1]) / 2.

    if not return_stddev:
        return bin_cents, ps1D
    else:
        ps1D_stddev = binned_statistic(dist_arr.ravel(),
                                       psd2.ravel(),
                                       bins=bins,
                                       statistic=np.nanstd)[0]
        return bin_cents, ps1D, ps1D_stddev


def make_radial_arrays(shape):

    y = np.arange(-np.floor(shape[0] / 2.).astype(int),
                  shape[0] - np.floor(shape[0] / 2.).astype(int))
    x = np.arange(-np.floor(shape[1] / 2.).astype(int),
                  shape[1] - np.floor(shape[1] / 2.).astype(int))

    yy, xx = np.meshgrid(y, x, indexing='ij')

    return yy, xx


def make_radial_freq_arrays(shape):

    yfreqs = np.fft.fftshift(np.fft.fftfreq(shape[0]))
    xfreqs = np.fft.fftshift(np.fft.fftfreq(shape[1]))

    yy_freq, xx_freq = np.meshgrid(yfreqs, xfreqs, indexing='ij')

    return yy_freq, xx_freq

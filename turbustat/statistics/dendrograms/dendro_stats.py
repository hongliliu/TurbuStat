# Licensed under an MIT open source license - see LICENSE
from __future__ import print_function, absolute_import, division

'''

Dendrogram statistics as described in Burkhart et al. (2013)
Two statistics are contained:
    * number of leaves + branches vs. $\delta$ parameter
    * statistical moments of the intensity histogram

Requires the astrodendro package (http://github.com/astrodendro/dendro-core)

'''

import numpy as np
from copy import deepcopy
from warnings import warn
import statsmodels.api as sm
import sys

if sys.version_info[0] >= 3:
    import _pickle as pickle
else:
    import cPickle as pickle


try:
    from astrodendro import Dendrogram, periodic_neighbours
    astrodendro_flag = True
except ImportError:
    Warning("Need to install astrodendro to use dendrogram statistics.")
    astrodendro_flag = False

from ..stats_utils import hellinger, common_histogram_bins, standardize
from ..base_statistic import BaseStatisticMixIn
from ...io import common_types, threed_types, twod_types
from .mecdf import mecdf


class Dendrogram_Stats(BaseStatisticMixIn):

    """
    Dendrogram statistics as described in Burkhart et al. (2013)
    Two statistics are contained:
    * number of leaves + branches vs. $\delta$ parameter
    * statistical moments of the intensity histogram

    Parameters
    ----------

    data : %(dtypes)s
        Data to create the dendrogram from.
    min_deltas : numpy.ndarray or list
        Minimum deltas of leaves in the dendrogram.
    dendro_params : dict
        Further parameters for the dendrogram algorithm
        (see www.dendrograms.org for more info).

    """

    __doc__ %= {"dtypes": " or ".join(common_types + twod_types +
                                      threed_types)}

    def __init__(self, data, header=None, min_deltas=None, dendro_params=None):
        super(Dendrogram_Stats, self).__init__()

        if not astrodendro_flag:
            raise ImportError("astrodendro must be installed to use "
                              "Dendrogram_Stats.")

        self.input_data_header(data, header)

        if dendro_params is None:
            self.dendro_params = {"min_npix": 10,
                                  "min_value": 0.001,
                                  "min_delta": 0.1}
        else:
            self.dendro_params = dendro_params

        self.min_deltas = min_deltas

    @property
    def min_deltas(self):
        '''
        Array of min_delta values to compute the dendrogram.
        '''
        return self._min_deltas

    @min_deltas.setter
    def min_deltas(self, value):
        # In the case where only one min_delta is given
        if "min_delta" in self.dendro_params and value is None:
            self._min_deltas = np.array([self.dendro_params["min_delta"]])
        elif not isinstance(value, np.ndarray):
            self._min_deltas = np.array([value])
        else:
            self._min_deltas = value

    def compute_dendro(self, verbose=False, save_dendro=False,
                       dendro_name=None, dendro_obj=None,
                       periodic_bounds=False):
        '''
        Compute the dendrogram and prune to the minimum deltas.
        ** min_deltas must be in ascending order! **

        Parameters
        ----------
        verbose : optional, bool
            Enables the progress bar in astrodendro.
        save_dendro : optional, bool
            Saves the dendrogram in HDF5 format. **Requires pyHDF5**
        dendro_name : str, optional
            Save name when save_dendro is enabled. ".hdf5" appended
            automatically.
        dendro_obj : Dendrogram, optional
            Input a pre-computed dendrogram object. It is assumed that
            the dendrogram has already been computed!
        periodic_bounds : bool, optional
            Enable when the data is periodic in the spatial dimensions.
        '''

        self._numfeatures = np.empty(self.min_deltas.shape, dtype=int)
        self._values = []

        if dendro_obj is None:
            if periodic_bounds:
                # Find the spatial dimensions
                num_axes = self.data.ndim
                spat_axes = []
                for i, axis_type in enumerate(self._wcs.get_axis_types()):
                    if axis_type["coordinate_type"] == u"celestial":
                        spat_axes.append(num_axes - i - 1)
                neighbours = periodic_neighbours(spat_axes)
            else:
                neighbours = None

            d = Dendrogram.compute(self.data, verbose=verbose,
                                   min_delta=self.min_deltas[0],
                                   min_value=self.dendro_params["min_value"],
                                   min_npix=self.dendro_params["min_npix"],
                                   neighbours=neighbours)
        else:
            d = dendro_obj
        self._numfeatures[0] = len(d)
        self._values.append(np.array([struct.vmax for struct in
                                      d.all_structures]))

        if len(self.min_deltas) > 1:
            for i, delta in enumerate(self.min_deltas[1:]):
                if verbose:
                    print("On %s of %s" % (i + 1, len(self.min_deltas[1:])))
                d.prune(min_delta=delta)
                self._numfeatures[i + 1] = len(d)
                self._values.append(np.array([struct.vmax for struct in
                                              d.all_structures]))

    @property
    def numfeatures(self):
        '''
        Number of branches and leaves at each value of min_delta
        '''
        return self._numfeatures

    @property
    def values(self):
        '''
        Array of peak intensity values of leaves and branches at all values of
        min_delta.
        '''
        return self._values

    def make_hists(self, min_number=10, **kwargs):
        '''
        Creates histograms based on values from the tree.
        *Note:* These histograms are remade when calculating the distance to
        ensure the proper form for the Hellinger distance.

        Parameters
        ----------
        min_number : int, optional
            Minimum number of structures needed to create a histogram.
        '''

        hists = []

        for value in self.values:

            if len(value) < min_number:
                hists.append([np.zeros((0, ))] * 2)
                continue

            if 'bins' not in kwargs:
                bins = int(np.sqrt(len(value)))
            else:
                bins = kwargs['bins']
                kwargs.pop('bins')

            hist, bins = np.histogram(value, bins=bins, **kwargs)
            bin_cents = (bins[:-1] + bins[1:]) / 2
            hists.append([bin_cents, hist])

        self._hists = hists

    @property
    def hists(self):
        '''
        Histogram values and bins computed from the peak intensity in all
        structures. One set of values and bins are returned for each value
        of `~Dendro_Statistics.min_deltas`
        '''
        return self._hists

    def fit_numfeat(self, size=5, verbose=False):
        '''
        Fit a line to the power-law tail. The break is approximated using
        a moving window, computing the standard deviation. A spike occurs at
        the break point.

        Parameters
        ----------
        size : int. optional
            Size of std. window. Passed to std_window.
        verbose : bool, optional
            Shows the model summary.
        '''

        if len(self.numfeatures) == 1:
            warn("Multiple min_delta values must be provided to perform"
                 " fitting. Only one value was given.")
            return

        nums = self.numfeatures[self.numfeatures > 1]
        deltas = self.min_deltas[self.numfeatures > 1]

        # Find the position of the break
        break_pos = std_window(nums, size=size)
        self.break_pos = deltas[break_pos]

        # Remove points where there is only 1 feature or less.
        self._fitvals = [np.log10(deltas[break_pos:]),
                         np.log10(nums[break_pos:])]

        x = sm.add_constant(self.fitvals[0])

        self._model = sm.OLS(self.fitvals[1], x).fit()

        if verbose:
            print(self.model.summary())

        errors = self.model.bse

        self._tail_slope = self.model.params[-1]
        self._tail_slope_err = errors[-1]

    @property
    def model(self):
        '''
        Power-law tail fit model.
        '''
        return self._model

    @property
    def fitvals(self):
        '''
        Log values of delta and number of structures used for the power-law
        tail fit.
        '''
        return self._fitvals

    @property
    def tail_slope(self):
        '''
        Slope of power-law tail.
        '''
        return self._tail_slope

    @property
    def tail_slope_err(self):
        '''
        1-sigma error on slope of power-law tail.
        '''
        return self._tail_slope_err

    def save_results(self, output_name=None, keep_data=False):
        '''
        Save the results of the dendrogram statistics to avoid re-computing.
        The pickled file will not include the data cube by default.
        '''

        if output_name is None:
            output_name = "dendrogram_stats_output.pkl"

        if output_name[-4:] != ".pkl":
            output_name += ".pkl"

        self_copy = deepcopy(self)

        # Don't keep the whole cube unless keep_data enabled.
        if not keep_data:
            self_copy.cube = None

        with open(output_name, 'wb') as output:
            pickle.dump(self_copy, output, -1)

    @staticmethod
    def load_results(pickle_file):
        '''
        Load in a saved pickle file.

        Parameters
        ----------
        pickle_file : str
            Name of filename to load in.
        '''

        with open(pickle_file, 'rb') as input:
            self = pickle.load(input)

        return self

    @staticmethod
    def load_dendrogram(hdf5_file, min_deltas=None):
        '''
        Load in a previously saved dendrogram. **Requires pyHDF5**

        Parameters
        ----------
        hdf5_file : str
            Name of saved file.
        min_deltas : numpy.ndarray or list
            Minimum deltas of leaves in the dendrogram.
        '''

        dendro = Dendrogram.load_from(hdf5_file)

        self = Dendrogram_Stats(dendro.data, min_deltas=min_deltas,
                                dendro_params=dendro.params)

        self.compute_dendro(dendro_obj=dendro)

        return self

    def run(self, periodic_bounds=False, verbose=False, save_name=None,
            dendro_verbose=False, dendro_obj=None, save_results=False,
            output_name=None, make_hists=True, **kwargs):
        '''

        Compute dendrograms. Necessary to maintain the package format.

        Parameters
        ----------
        periodic_bounds : bool or list, optional
            Enable when the data is periodic in the spatial dimensions. Passing
            a two-element list can be used to individually set how the
            boundaries are treated for the datasets.
        verbose : optional, bool
            Enable plotting of results.
        save_name : str,optional
            Save the figure when a file name is given.
        dendro_verbose : optional, bool
            Prints out updates while making the dendrogram.
        dendro_obj : Dendrogram, optional
            Pass a pre-computed dendrogram object. **MUST have min_delta set
            at or below the smallest value in`~Dendro_Statistics.min_deltas`.**
        save_results : bool, optional
            Save the statistic results as a pickle file. See
            `~Dendro_Statistics.save_results`.
        output_name : str, optional
            Filename used when `save_results` is enabled. Must be given when
            saving.
        make_hists : bool, optional
            Enable computing histograms.
        kwargs : Passed to `~Dendro_Statistics.make_hists`.
        '''
        self.compute_dendro(verbose=dendro_verbose, dendro_obj=dendro_obj,
                            periodic_bounds=periodic_bounds)
        self.fit_numfeat(verbose=verbose)

        if make_hists:
            self.make_hists(**kwargs)

        if verbose:
            import matplotlib.pyplot as p

            if not make_hists:
                ax1 = p.subplot(111)
            else:
                ax1 = p.subplot(121)

            ax1.plot(self.fitvals[0], self.fitvals[1], 'bD')
            ax1.plot(self.fitvals[0], self.model.fittedvalues, 'g')
            p.xlabel(r"log $\delta$")
            p.ylabel(r"log Number of Features")

            if make_hists:
                ax2 = p.subplot(122)

                for bins, vals in self.hists:
                    if bins.size < 1:
                        continue
                    bin_width = np.abs(bins[1] - bins[0])
                    ax2.bar(bins, vals, align="center",
                            width=bin_width, alpha=0.25)
                    p.xlabel("Data Value")

            if save_name is not None:
                p.savefig(save_name)
                p.close()
            else:
                p.show()

        if save_results:
            self.save_results(output_name=output_name)


class DendroDistance(object):

    """
    Calculate the distance between 2 cubes using dendrograms. The number of
    features vs. minimum delta is fit to a linear model, with an interaction
    term o gauge the difference. The distance is the t-statistic of that
    parameter. The Hellinger distance is computed for the histograms at each
    minimum delta value. The distance is the average of the Hellinger
    distances.

    Parameters
    ----------
    cube1 : %(dtypes)s or str
        Data cube. If a str, it should be the filename of a pickle file saved
        using Dendrogram_Stats.
    cube2 : %(dtypes)s or str
        Data cube. If a str, it should be the filename of a pickle file saved
        using Dendrogram_Stats.
    min_deltas : numpy.ndarray or list
        Minimum deltas of leaves in the dendrogram.
    nbins : str or float, optional
        Number of bins for the histograms. 'best' sets
        that number using the square root of the average
        number of features between the histograms to be
        compared.
    min_features : int, optional
        The minimum number of features necessary to compare
        the histograms.
    fiducial_model : Dendrogram_Stats
        Computed dendrogram and statistic values. Use to avoid
        re-computing.
    dendro_params : dict or list of dicts, optional
        Further parameters for the dendrogram algorithm
        (see www.dendrograms.org for more info). If a list of dictionaries is
        given, the first list entry should be the dictionary for cube1, and the
        second for cube2.
    periodic_bounds : bool or list, optional
        Enable when the data is periodic in the spatial dimensions. Passing
        a two-element list can be used to individually set how the boundaries
        are treated for the datasets.
    """

    __doc__ %= {"dtypes": " or ".join(common_types + twod_types +
                                      threed_types)}

    def __init__(self, cube1, cube2, min_deltas=None, nbins="best",
                 min_features=100, fiducial_model=None, dendro_params=None,
                 periodic_bounds=False):
        super(DendroDistance, self).__init__()

        if not astrodendro_flag:
            raise ImportError("astrodendro must be installed to use "
                              "Dendrogram_Stats.")

        self.nbins = nbins

        if min_deltas is None:
            # min_deltas = np.append(np.logspace(-1.5, -0.7, 8),
            #                        np.logspace(-0.6, -0.35, 10))
            min_deltas = np.logspace(-2.5, 0.5, 100)

        if dendro_params is not None:
            if isinstance(dendro_params, list):
                dendro_params1 = dendro_params[0]
                dendro_params2 = dendro_params[1]
            elif isinstance(dendro_params, dict):
                dendro_params1 = dendro_params
                dendro_params2 = dendro_params
            else:
                raise TypeError("dendro_params is a {}. It must be a dictionary"
                                ", or a list containing a dictionary entries."
                                .format(type(dendro_params)))
        else:
            dendro_params1 = None
            dendro_params2 = None

        if isinstance(periodic_bounds, bool):
            periodic_bounds = [periodic_bounds] * 2
        else:
            if not len(periodic_bounds) == 2:
                raise ValueError("periodic_bounds should be a two-element"
                                 " list.")

        if fiducial_model is not None:
            self.dendro1 = fiducial_model
        elif isinstance(cube1, str):
            self.dendro1 = Dendrogram_Stats.load_results(cube1)
        else:
            self.dendro1 = Dendrogram_Stats(
                cube1, min_deltas=min_deltas, dendro_params=dendro_params1)
            self.dendro1.run(verbose=False, make_hists=False,
                             periodic_bounds=periodic_bounds[0])

        if isinstance(cube2, str):
            self.dendro2 = Dendrogram_Stats.load_results(cube2)
        else:
            self.dendro2 = \
                Dendrogram_Stats(cube2, min_deltas=min_deltas,
                                 dendro_params=dendro_params2)
            self.dendro2.run(verbose=False, make_hists=False,
                             periodic_bounds=periodic_bounds[1])

        # Set the minimum number of components to create a histogram
        cutoff1 = np.argwhere(self.dendro1.numfeatures > min_features)
        cutoff2 = np.argwhere(self.dendro2.numfeatures > min_features)
        if cutoff1.any():
            cutoff1 = cutoff1[-1]
        else:
            raise ValueError("The dendrogram from cube1 does not contain the"
                             " necessary number of features, %s. Lower"
                             " min_features or alter min_deltas."
                             % (min_features))
        if cutoff2.any():
            cutoff2 = cutoff2[-1]
        else:
            raise ValueError("The dendrogram from cube2 does not contain the"
                             " necessary number of features, %s. Lower"
                             " min_features or alter min_deltas."
                             % (min_features))

        self.cutoff = np.min([cutoff1, cutoff2])

        self.bins = []
        self.mecdf1 = None
        self.mecdf2 = None

        self.num_results = None
        self.num_distance = None
        self.histogram_distance = None

    def numfeature_stat(self, verbose=False, label1=None, label2=None,
                        save_name=None):
        '''
        Calculate the distance based on the number of features statistic.

        Parameters
        ----------
        verbose : bool, optional
            Enables plotting.
        label1 : str, optional
            Object or region name for cube1
        label2 : str, optional
            Object or region name for cube2
        save_name : str, optional
            Saves the plot when a filename is given.
        '''

        self.num_distance = \
            np.abs(self.dendro1.tail_slope - self.dendro2.tail_slope) / \
            np.sqrt(self.dendro1.tail_slope_err**2 +
                    self.dendro2.tail_slope_err**2)

        if verbose:

            import matplotlib.pyplot as p

            # Dendrogram 1
            p.plot(self.dendro1.fitvals[0], self.dendro1.fitvals[1], 'bD',
                   label=label1)
            p.plot(self.dendro1.fitvals[0], self.dendro1.model.fittedvalues,
                   'b')

            # Dendrogram 2
            p.plot(self.dendro2.fitvals[0], self.dendro2.fitvals[1], 'go',
                   label=label2)
            p.plot(self.dendro2.fitvals[0], self.dendro2.model.fittedvalues,
                   'g')

            p.grid(True)
            p.xlabel(r"log $\delta$")
            p.ylabel("log Number of Features")
            p.legend(loc='best')

            if save_name is not None:
                p.savefig(save_name)
                p.clf()
            else:
                p.show()

        return self

    def histogram_stat(self, verbose=False, label1=None, label2=None,
                       save_name=None):
        '''
        Computes the distance using histograms.

        Parameters
        ----------
        verbose : bool, optional
            Enables plotting.
        label1 : str, optional
            Object or region name for cube1
        label2 : str, optional
            Object or region name for cube2
        save_name : str, optional
            Saves the plot when a filename is given.
        '''

        if self.nbins == "best":
            self.nbins = [np.floor(np.sqrt((n1 + n2) / 2.)) for n1, n2 in
                          zip(self.dendro1.numfeatures[:self.cutoff],
                              self.dendro2.numfeatures[:self.cutoff])]
        else:
            self.nbins = [self.nbins] * \
                len(self.dendro1.numfeatures[:self.cutoff])

        self.nbins = np.array(self.nbins, dtype=int)

        self.histograms1 = \
            np.empty((len(self.dendro1.numfeatures[:self.cutoff]),
                      np.max(self.nbins)))
        self.histograms2 = \
            np.empty((len(self.dendro2.numfeatures[:self.cutoff]),
                      np.max(self.nbins)))

        for n, (data1, data2, nbin) in enumerate(
                zip(self.dendro1.values[:self.cutoff],
                    self.dendro2.values[:self.cutoff], self.nbins)):

            stand_data1 = standardize(data1)
            stand_data2 = standardize(data2)

            bins = common_histogram_bins(stand_data1, stand_data2,
                                         nbins=nbin + 1)

            self.bins.append(bins)

            hist1 = np.histogram(stand_data1, bins=bins,
                                 density=True)[0]
            self.histograms1[n, :] = \
                np.append(hist1, (np.max(self.nbins) -
                                  bins.size + 1) * [np.NaN])

            hist2 = np.histogram(stand_data2, bins=bins,
                                 density=True)[0]
            self.histograms2[n, :] = \
                np.append(hist2, (np.max(self.nbins) -
                                  bins.size + 1) * [np.NaN])

            # Normalize
            self.histograms1[n, :] /= np.nansum(self.histograms1[n, :])
            self.histograms2[n, :] /= np.nansum(self.histograms2[n, :])

        self.mecdf1 = mecdf(self.histograms1)
        self.mecdf2 = mecdf(self.histograms2)

        self.histogram_distance = hellinger_stat(
            self.histograms1, self.histograms2)

        if verbose:
            import matplotlib.pyplot as p

            ax1 = p.subplot(2, 2, 1)
            ax1.set_title(label1)
            ax1.set_ylabel("ECDF")
            for n in range(len(self.dendro1.min_deltas[:self.cutoff])):
                ax1.plot((self.bins[n][:-1] + self.bins[n][1:]) / 2,
                         self.mecdf1[n, :][:self.nbins[n]])
            ax1.axes.xaxis.set_ticklabels([])
            ax2 = p.subplot(2, 2, 2)
            ax2.set_title(label2)
            ax2.axes.xaxis.set_ticklabels([])
            ax2.axes.yaxis.set_ticklabels([])
            for n in range(len(self.dendro2.min_deltas[:self.cutoff])):
                ax2.plot((self.bins[n][:-1] + self.bins[n][1:]) / 2,
                         self.mecdf2[n, :][:self.nbins[n]])
            ax3 = p.subplot(2, 2, 3)
            ax3.set_ylabel("PDF")
            for n in range(len(self.dendro1.min_deltas[:self.cutoff])):
                bin_width = self.bins[n][1] - self.bins[n][0]
                ax3.bar((self.bins[n][:-1] + self.bins[n][1:]) / 2,
                        self.histograms1[n, :][:self.nbins[n]],
                        align="center", width=bin_width, alpha=0.25)
            ax3.set_xlabel("z-score")
            ax4 = p.subplot(2, 2, 4)
            for n in range(len(self.dendro2.min_deltas[:self.cutoff])):
                bin_width = self.bins[n][1] - self.bins[n][0]
                ax4.bar((self.bins[n][:-1] + self.bins[n][1:]) / 2,
                        self.histograms2[n, :][:self.nbins[n]],
                        align="center", width=bin_width, alpha=0.25)
            ax4.set_xlabel("z-score")
            ax4.axes.yaxis.set_ticklabels([])

            p.tight_layout()
            if save_name is not None:
                p.savefig(save_name)
                p.clf()
            else:
                p.show()

        return self

    def distance_metric(self, verbose=False, label1=None, label2=None):
        '''
        Calculate both distance metrics.

        Parameters
        ----------
        verbose : bool, optional
            Enables plotting.
        label1 : str, optional
            Object or region name for cube1
        label2 : str, optional
            Object or region name for cube2
        '''

        self.histogram_stat(verbose=verbose, label1=label1, label2=label2)
        self.numfeature_stat(verbose=verbose, label1=label1, label2=label2)

        return self


def hellinger_stat(x, y):
    '''
    Compute the Hellinger statistic of multiple samples.
    '''

    assert x.shape == y.shape

    if len(x.shape) == 1:
        return hellinger(x, y)
    else:
        dists = np.empty((x.shape[0], 1))
        for n in range(x.shape[0]):
            dists[n, 0] = hellinger(x[n, :], y[n, :])
        return np.mean(dists)


def std_window(y, size=5, return_results=False):
    '''
    Uses a moving standard deviation window to find where the powerlaw break
    is.

    Parameters
    ----------
    y : np.ndarray
        Data.
    size : int, optional
        Odd integer which sets the window size.
    return_results : bool, optional
        If enabled, returns the results of the window. Otherwise, only the
        position of the break is returned.
    '''

    half_size = (size - 1) // 2

    shape = max(y.shape)

    stds = np.empty((shape - size + 1))

    for i in range(half_size, shape - half_size):
        stds[i - half_size] = np.std(y[i - half_size: i + half_size])

    # Now find the max
    break_pos = np.argmax(stds) + half_size

    if return_results:
        return break_pos, stds

    return break_pos

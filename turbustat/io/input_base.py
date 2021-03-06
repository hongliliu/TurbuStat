# Licensed under an MIT open source license - see LICENSE
from __future__ import print_function, absolute_import, division

from astropy.io.fits.hdu.image import _ImageBaseHDU
from astropy.io import fits
from spectral_cube import SpectralCube
from spectral_cube.lower_dimensional_structures import LowerDimensionalObject
import numpy as np


common_types = ["numpy.ndarray", "astropy.io.fits.PrimaryHDU",
                "astropy.io.fits.ImageHDU"]
twod_types = ["spectral_cube.Projection", "spectral_cube.Slice"]
threed_types = ["SpectralCube"]


def input_data(data, no_header=False):
    '''
    Accept a variety of input data forms and return those expected by the
    various statistics.

    Parameters
    ----------
    data : astropy.io.fits.PrimaryHDU, spectral_cube.SpectralCube,
           spectral_cube.Projection, spectral_cube.Slice, np.ndarray or a
           tuple/listwith the data and the header
        Data to be used with a given statistic or distance metric. no_header
        must be enabled when passing only an array in.
    no_header : bool, optional
        When enabled, returns only the data without the header.

    Returns
    -------
    ouput_data : tuple or np.ndarray
        A tuple containing the data and the header. Or an array when no_header
        is enabled.
    '''

    if isinstance(data, _ImageBaseHDU):
        output_data = [data.data, data.header]
    elif isinstance(data, SpectralCube):
        output_data = [data.filled_data[:].value, data.header]
    elif isinstance(data, LowerDimensionalObject):
        output_data = [data.value, data.header]
    elif isinstance(data, tuple) or isinstance(data, list):
        if len(data) != 2:
            raise TypeError("Must have two items: data and the header.")
        output_data = data
    elif isinstance(data, np.ndarray):
        if not no_header:
            raise TypeError("no_header must be enabled when giving data"
                            " without a header.")
        output_data = [data]
    else:
        raise TypeError("Input data is not of an accepted form:"
                        " astropy.io.fits.PrimaryHDU, astropy.io.fits.ImageHDU,"
                        " spectral_cube.SpectralCube,"
                        " spectral_cube.LowerDimensionalObject or a tuple or"
                        " list containing the data and header, in that order.")

    if no_header:
        return output_data[0]

    return output_data


def to_spectral_cube(data, header):
    '''
    Convert the output from input_data into a SpectralCube.
    '''

    hdu = fits.PrimaryHDU(data, header)

    return SpectralCube.read(hdu)

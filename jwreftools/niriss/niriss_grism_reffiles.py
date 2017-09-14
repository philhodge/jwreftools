import re
import datetime
import numpy as np
from asdf.tags.core import Software, HistoryEntry
from astropy.modeling.models import Polynomial2D, Polynomial1D
from astropy.io import fits
from astropy import units as u

from jwst.datamodels import NIRISSGrismModel
from jwst.datamodels import wcs_ref_models


def common_reference_file_keywords(reftype=None,
                                   author="STScI",
                                   exp_type=None,
                                   description="NIRISS Reference File",
                                   title="NIRISS Reference File",
                                   useafter="2014-01-01T00:00:00",
                                   filtername=None,
                                   filename="",
                                   pupil=None, **kwargs):
    """
    exp_type can be also "N/A", or "ANY".
    """
    if exp_type is None:
        raise ValueError("Expected exp_type")
    if reftype is None:
        raise ValueError("Expected reftype")

    ref_file_common_keywords = {
        "author": author,
        "description": description,
        "exposure": {"type": exp_type},
        "instrument": {"name": "NIRISS",
                       "detector": "NIS"},
        "pedigree": "ground",
        "reftype": reftype,
        "telescope": "JWST",
        "title": title,
        "useafter": useafter,
        "filename": filename,
        }

    if filtername is not None:
        ref_file_common_keywords["instrument"]["filter"] = filtername
    if pupil is not None:
        ref_file_common_keywords["instrument"]["pupil"] = pupil

    ref_file_common_keywords.update(kwargs)
    return ref_file_common_keywords


def create_grism_config(conffile="",
                        fname="",
                        pupil="",
                        author="STScI",
                        history="NIRISS Grism Parameters",
                        outname=""):
    """
    pupil is the blocking filter
    filter is the grism

    Create an asdf reference file to hold Grism C (column) or Grism R (rows)
    configuration, no sensativity information is included

    Note: The orders are named alphabetically, i.e. Order A, Order B
    There are also sensativity fits files which are tables of wavelength,
    sensativity, and error. These are specified in the conffile but will
    not be read in and saved in the output reference file.

    direct_filter is not specified because it assumes that the wedge
    information (wx,wy) is included in the conf file in one of the key-value
    pairs, where the key includes the beam designation

    For each spectral order, the configuration file contains a pair of
    magnitude-cutoff values. Sources with magnitudes fainter than the
    extraction cutoff (MMAG_EXTRACT_X) are not extracted, but are accounted
    for when computing the spectral contamination and background estimates.
    Sources with magnitudes fainter than the second cutoff (MMAG_MARK_X) are
    completely ignored.  Here, X equals A, B, C, etc., with each letter
    referring to a spectral order, as specified in the configuration file.
     -- the initial conf file that nor gave me didn't have this keyword so
     this code adds a placeholder.

     this reference file also contains the polynomial model which is appropriate
     for the coefficients which are listed.

    Parameters
    ----------
    conffile : str
        The text file with configuration information
    pupil : str
        Name of the grism the conffile corresponds to
    filter : str
        Name of the filter the conffile corresponds to
    author : str
        The name of the author
    history : str
        A comment about the refrence file to be saved with the meta information
    outname : str
        Output name for the reference file


    Returns
    -------
    fasdf : asdf.AsdfFile(jwst.datamodels.NIRISSGrismModel)
    """

    if not history:
        history = "Created from {0:s}".format(conffile)

    # if pupil is none get from filename like NIRCAM_modB_R.conf
    if not fname:
        fname = conffile.split(".")[0]
    if not pupil:
        pupil = conffile.split(".")[1]

    ref_kw = common_reference_file_keywords(reftype="specwcs",
                description="{0:s} dispersion model parameters".format(pupil),
                exp_type="NIS_WFSS",
                model_type='NIRISSGrismModel',
                pupil=pupil,
                filtername=fname,
                history=history,
                author=author,
                filename=outname,
                )

    # get all the key-value pairs from the input file
    conf = dict_from_file(conffile)
    beamdict = split_order_info(conf)
    letter = re.compile("^[a-zA-Z0-9]{0,1}$")  # match one only
    etoken = re.compile("^BEAM_[A-Z,a-z]{1,1}")  # find beam key

    # add min and max mag info if not provided
    # also make beam coeff lists
    # wx are the wedge offsets for the filters
    # in niriss there's a different grism file for each filter

    # for k, bdict in beamdict.items():
    #     if isinstance(bdict, dict):
    #         keys = bdict.keys()
    #         minmag = "MMAG_EXTRACT"
            # maxmag = "MMAG_MARK"
            # if minmag not in keys:
            #     beamdict[k][minmag] = 99.
            # if maxmag not in keys:
            #    beamdict[k][maxmag] = 0.0
            # if "wx" not in keys:
            #    beamdict[k]['wx'] = 0.0
            # if "wy" not in keys:
            #    beamdict[k]['wy'] = 0.0

    # add to the big tree
    # tree['spectral_orders'] = beamdict

    # add the polynomial model for this file.
    # this structure allows there to be a different polynomial relationship
    # for each order if necessary. Either way, the coefficients should be
    # stored with the polynomials since they are directly dependent on
    # each other
    # for order in tree['spectral_orders']:
    #     print("order: {}".format(order))
    #     xc = tree['spectral_orders'][order]["DISPX"]
    #     yc = tree['spectral_orders'][order]["DISPY"]
    #     lc = tree['spectral_orders'][order]["DISPL"]
    #     print("{} {} {}".format(xc, yc, lc))
    #     model = models.PolyTraceDispersion(xc, yc, lc, w)
    #     tree['spectral_orders'][order]['model'] = model

    # The lists below need
    # to remain ordered and referenced by filter or order
    orders = sorted(beamdict.keys())

    # disp[] per sorted order
    displ = []
    dispx = []
    dispy = []
    invdispl = []

    for order in orders:
        # convert the displ wavelengths to microns
        l0 = beamdict[order]['DISPL'][0] / 10000.
        l1 = beamdict[order]['DISPL'][1] / 10000.
        # create polynomials for the coefficients of each order
        invdispl.append(Polynomial1D(1, c0=-l0/l1, c1=1./l1))
        displ.append(Polynomial1D(1, c0=l0, c1=l1))

        # the dispxy functions here are pulled into a 1D
        # such that the final poly is ans = x_model + t*y_model

        e0, e1 = beamdict[order]['DISPX']
        model_x = Polynomial2D(2, c0_0=e0[0], c1_0=e0[1], c2_0=e0[4],
                               c0_1=e0[2], c1_1=e0[5], c0_2=e0[3])
        model_y = Polynomial2D(2, c0_0=e1[0], c1_0=e1[1], c2_0=e1[4],
                               c0_1=e1[2], c1_1=e1[5], c0_2=e1[3])
        dispx.append((model_x, model_y))

        e0, e1 = beamdict[order]['DISPY']
        model_x = Polynomial2D(2, c0_0=e0[0], c1_0=e0[1], c2_0=e0[4],
                               c0_1=e0[2], c1_1=e0[5], c0_2=e0[3])
        model_y = Polynomial2D(2, c0_0=e1[0], c1_0=e1[1], c2_0=e1[4],
                               c0_1=e1[2], c1_1=e1[5], c0_2=e1[3])
        dispy.append((model_x, model_y))
        # disp is x_model + t*y_model
        # invdisp is (t - model_x) / model_y

    # change the orders into translatable integer strings
    # the conf file niriss is giving me are using letter designations
    beam_lookup = {"A": "+1", "B": "0", "C": "+2", "D": "+3", "E": "-1"}
    ordermap = [int(beam_lookup[order]) for order in orders]

    # save the reference file
    ref = NIRISSGrismModel()
    ref.meta.update(ref_kw)
    ref.meta.input_units = u.micron
    ref.meta.output_units = u.micron
    ref.dispx = dispx
    ref.dispy = dispy
    ref.displ = displ
    ref.invdispl = invdispl
    ref.fwcpos_ref = conf['FWCPOS_REF']
    ref.orders = ordermap
    entry = HistoryEntry({'description': history, 'time': datetime.datetime.utcnow()})
    sdict = Software({'name': 'niriss_reftools.py',
                      'author': author,
                      'homepage': 'https://github.com/spacetelescope/jwreftools',
                      'version': '0.7.1'})
    entry['sofware'] = sdict
    ref.history = [entry]
    ref.to_asdf(outname)
    ref.validate()


def create_grism_waverange(outname="",
                           history="NIRCAM Grism wavelengthrange",
                           author="STScI",
                           module="N/A",
                           pupil="N/A",
                           filter_range=None):
    """Create a wavelengthrange reference file. There is a different file for each filter

    Supply a filter range dictionary or use the default

    """
    ref_kw = common_reference_file_keywords(reftype="wavelengthrange",
                                            title="NIRISS WFSS waverange",
                                            exp_type="NIS_WFSS",
                                            description="NIRISS WFSS Filter Wavelength Ranges",
                                            useafter="2014-01-01T00:00:00",
                                            author=author,
                                            model_type="WavelengthrangeModel",
                                            module=module,
                                            pupil=None,
                                            filename=outname,
                                            filtername=None)

    if filter_range is None:
        # These numbers from Grabriel Brammer, in microns
        # There is only one set of ranges because they are
        # valid for all orders listed, the wavelengthrange
        # file requires a double array by order, so they
        # will be replicated for each order, this allows
        # allows adaptation for future updates per order
        filter_range = {'F090W': [0.79, 1.03],
                        'F115W': [0.97, 1.32],
                        'F140M': [1.29, 1.52],
                        'F150W': [1.29, 1.71],
                        'F158M': [1.41, 1.74],
                        'F200W': [1.70, 2.28]
                        }
        orders = [-1, 0, 1, 2, 3]
    else:
        # array of integers
        orders = list(filter_range.keys())
        orders.sort()

    # same filters for every order, array of strings
    wrange_selector = list(filter_range.keys())
    wrange_selector.sort()

    # The lists below need
    # to remain ordered to be correctly referenced
    wavelengthrange = []
    for order in orders:
        o = []
        for fname in wrange_selector:
            o.append(filter_range[fname])
        wavelengthrange.append(o)

    ref = wcs_ref_models.WavelengthrangeModel()
    ref.meta.update(ref_kw)
    ref.meta.input_units = u.micron
    ref.meta.output_units = u.micron
    ref.wrange_selector = wrange_selector
    ref.wrange = wavelengthrange
    ref.order = orders
    entry = HistoryEntry({'description': history, 'time': datetime.datetime.utcnow()})
    sdict = Software({'name': 'niriss_reftools.py',
                      'author': author,
                      'homepage': 'https://github.com/spacetelescope/jwreftools',
                      'version': '0.7.1'})
    entry['sofware'] = sdict
    ref.history = [entry]
    ref.to_asdf(outname)
    ref.validate()


def split_order_info(keydict):
    """Accumulate keys just for each Beam/order.

    Designed to take as input the dictionary created by dict_from_file
    split out and accumulate the keys for each beam/order.
    The keys must have the beam in their string, the spurious beam designation
    is removed from the returned dictionary. Keywords with the same first name
    in the underscore separated string followed by a number are assumed to be
    ranges


    Parameters
    ----------
    keydict : dictionary
        Dictionary of key value pairs

    Returns
    -------
    dictionary of beams, where each beam has a dictionary of key-value pairs
    Any key pairs which are not associated with a beam get a separate entry
    """

    if not isinstance(keydict, dict):
        raise ValueError("Expected an input dictionary")

    # has beam name fits token
    # token = re.compile('^[a-zA-Z]*_(?:[+\-]){0,1}[a-zA-Z0-9]{1}_{1}')
    token = re.compile('^[a-zA-Z]*_[a-zA-Z0-9]{1}_(?:\w)')
    rangekey = re.compile('^[a-zA-Z]*_[0-1]{1,1}$')
    rdict = dict()  # return dictionary
    beams = list()
    savekey = dict()

    # prefetch number of Beams, beam is the second string
    for key in keydict:
        if token.match(key):
            b = key.split("_")[1].upper()
            if b not in beams:
                beams.append(b)
                rdict[b] = dict()
            newkey = key.replace("_{}".format(b), "")
            rdict[b][newkey] = keydict[key]

    # look for range variables to make them into tuples
    for b, d in rdict.items():
        if isinstance(d, dict):
            keys = d.keys()
        else:
            keys = []
        rkeys = []
        odict = {}
        for k in keys:
            if rangekey.match(k):
                rkeys.append(k)
        for k in rkeys:
            mlist = [m for m in rkeys if k.split("_")[0] in m]
            root = mlist[0].split("_")[0]
            if root not in odict:
                for mk in mlist:
                    if eval(mk[-1]) == 0:
                        zero = d[mk]
                    elif eval(mk[-1]) == 1:
                        one = d[mk]
                    else:
                        raise ValueError("Unexpected range variable {}"
                                         .format(mk))
                odict[root] = (zero, one)
        # combine the dictionaries and remove the old keys
        if odict:
            d.update(odict)
        if rkeys:
            for k in rkeys:
                del d[k]

    return rdict


def dict_from_file(filename):
    """Read in a file and return a dict of the key value pairs.

    This is a generic read for a text file with the line following format:

    keyword<token>value

    Where keyword should start with a character, not a number
    Non-alphabetic starting characters are ignored
    <token> can be space or comma

    Parameters
    ----------
    filename : str
        Name of the file to interpret

    Examples
    --------
    dict_from_file('NIRISS_C.conf')

    Returns
    -------
    dictionary of deciphered keys and values

    """
    token = '\s+|(?<!\d)[,](?!\d)'
    letters = re.compile("(^[a-zA-Z])")  # starts with a letter
    numbers = re.compile("(^(?:[+\-])?(?:\d*)(?:\.)?(?:\d*)?(?:[eE][+\-]?\d*$)?)")
    empty = re.compile("(^\s*$)")  # is a blank line

    print("\nReading {0:s}  ...".format(filename))
    with open(filename, 'r') as fh:
        lines = fh.readlines()
    content = dict()
    for line in lines:
        value = None
        vallist = []
        key = None
        if not empty.match(line):
            if letters.match(line):
                pair = re.split(token, line.strip(), maxsplit=10)
                if len(pair) == 2:
                    key = pair[0]
                    if numbers.fullmatch(pair[1]):
                        value = eval(pair[1])
                else:  # more than 2 values
                    key = pair[0]
                    vals = pair[1:]
                    for v in vals:
                        if numbers.fullmatch(v):
                            vallist.append(eval(v))
                        else:
                            raise ValueError("Unexpected value for {0}"
                                             .format(key))

        if key:
            if (("FILTER" not in key) and ("SENS" not in key)):
                if (value is None):
                    content[key] = vallist
                    print("Setting {0:s} = {1}".format(key, vallist))
                else:
                    content[key] = value
                    print("Setting {0:s} = {1}".format(key, value))
    return content
#!/usr/bin/env python
#
# Author: Mike McKerns (mmckerns @caltech and @uqfoundation)
# Copyright (c) 2013-2015 California Institute of Technology.
# License: 3-clause BSD.  The full license text is available at:
#  - http://trac.mystic.cacr.caltech.edu/project/pathos/browser/klepto/LICENSE

from __future__ import absolute_import

# get version numbers, license, and long description
try:
    from .info import this_version as __version__
    from .info import readme as __doc__, license as __license__
except ImportError:
    msg = """First run 'python setup.py build' to build klepto."""
    raise ImportError(msg)

__author__ = 'Mike McKerns'

__doc__ = """
""" + __doc__

__license__ = """
""" + __license__


from ._cache import no_cache, inf_cache, lfu_cache, \
                    lru_cache, mru_cache, rr_cache
from ._inspect import signature, isvalid, validate, \
                      keygen, strip_markup, NULL, _keygen
from . import rounding
from . import safe
from . import archives
from . import keymaps
from . import tools
from . import crypto


def license():
    """print license"""
    print (__license__)
    return

def citation():
    """print citation"""
    print (__doc__[-247:-106])
    return

del absolute_import

# end of file

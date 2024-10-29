# Future imports for Python 2.7, mandatory in 3.0
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals


class NetworkTestFailure(Exception):
    """Raising this exception indicates that a test failed in some "normal" way"""

    pass

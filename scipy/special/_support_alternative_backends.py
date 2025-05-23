import functools
import operator

import numpy as np
from scipy._lib._array_api import (
    array_namespace, scipy_namespace_for, is_numpy, is_dask, is_marray,
    xp_promote, SCIPY_ARRAY_API
)
import scipy._lib.array_api_extra as xpx
from . import _ufuncs
# These don't really need to be imported, but otherwise IDEs might not realize
# that these are defined in this file / report an error in __init__.py
from ._ufuncs import (
    log_ndtr, ndtr, ndtri, erf, erfc, i0, i0e, i1, i1e, gammaln,  # noqa: F401
    gammainc, gammaincc, logit, expit, entr, rel_entr, xlogy,  # noqa: F401
    chdtr, chdtrc, betainc, betaincc, stdtr, stdtrit  # noqa: F401
)

array_api_compat_prefix = "scipy._lib.array_api_compat"


def get_array_special_func(f_name, xp):
    if is_numpy(xp):
        return getattr(_ufuncs, f_name)

    spx = scipy_namespace_for(xp)
    if spx is not None:
        f = getattr(spx.special, f_name, None)
        if f is not None:
            return f

    # if generic array-API implementation is available, use that;
    # otherwise, fall back to NumPy/SciPy
    if f_name in _generic_implementations:
        f = _generic_implementations[f_name](xp=xp, spx=spx)
        if f is not None:
            return f

    def f(*args, **kwargs):
        if is_marray(xp):
            _f = globals()[f_name]  # Allow nested wrapping
            data_args = [arg.data for arg in args]
            out = _f(*data_args, **kwargs)
            mask = functools.reduce(operator.or_, (arg.mask for arg in args))
            return xp.asarray(out, mask=mask)

        elif is_dask(xp):
            # IMPORTANT: map_blocks works only because all ufuncs in this module
            # are elementwise. It would be a grave mistake to apply this to gufuncs
            # or any other function with reductions, as they would change their
            # output depending on chunking!

            _f = globals()[f_name]  # Allow nested wrapping
            # Hide dtype kwarg from map_blocks
            return xp.map_blocks(functools.partial(_f, **kwargs), *args)

        else:
            _f = getattr(_ufuncs, f_name)
            args = [np.asarray(arg) for arg in args]
            out = _f(*args, **kwargs)
            return xp.asarray(out)

    return f


def _rel_entr(xp, spx):
    def __rel_entr(x, y, *, xp=xp):
        # https://github.com/data-apis/array-api-extra/issues/160
        mxp = array_namespace(x._meta, y._meta) if is_dask(xp) else xp
        x, y = xp_promote(x, y, broadcast=True, force_floating=True, xp=xp)
        xy_pos = (x > 0) & (y > 0)
        xy_inf = xp.isinf(x) & xp.isinf(y)
        res = xpx.apply_where(
            xy_pos & ~xy_inf,
            (x, y),
            # Note: for very large x, this can overflow.
            lambda x, y: x * (mxp.log(x) - mxp.log(y)),
            fill_value=xp.inf
        )
        res = xpx.at(res)[(x == 0) & (y >= 0)].set(0)
        res = xpx.at(res)[xp.isnan(x) | xp.isnan(y) | (xy_pos & xy_inf)].set(xp.nan)
        return res

    return __rel_entr


def _xlogy(xp, spx):
    def __xlogy(x, y, *, xp=xp):
        with np.errstate(divide='ignore', invalid='ignore'):
            temp = x * xp.log(y)
        return xp.where(x == 0., 0., temp)
    return __xlogy


def _get_native_func(xp, spx, f_name):
    f = getattr(spx.special, f_name, None) if spx else None
    if f is None and hasattr(xp, 'special'):
        f = getattr(xp.special, f_name, None)
    return f


def _chdtr(xp, spx):
    # The difference between this and just using `gammainc`
    # defined by `get_array_special_func` is that if `gammainc`
    # isn't found, we don't want to use the SciPy version; we'll
    # return None here and use the SciPy version of `chdtr`.
    gammainc = _get_native_func(xp, spx, 'gammainc')  # noqa: F811
    if gammainc is None:
        return None

    def __chdtr(v, x):
        res = gammainc(v / 2, x / 2)  # this is almost all we need
        # The rest can be removed when google/jax#20507 is resolved
        mask = (v == 0) & (x > 0)  # JAX returns NaN
        res = xp.where(mask, 1., res)
        mask = xp.isinf(v) & xp.isinf(x)  # JAX returns 1.0
        return xp.where(mask, xp.nan, res)
    return __chdtr


def _chdtrc(xp, spx):
    # The difference between this and just using `gammaincc`
    # defined by `get_array_special_func` is that if `gammaincc`
    # isn't found, we don't want to use the SciPy version; we'll
    # return None here and use the SciPy version of `chdtrc`.
    gammaincc = _get_native_func(xp, spx, 'gammaincc')  # noqa: F811
    if gammaincc is None:
        return None

    def __chdtrc(v, x):
        res = xp.where(x >= 0, gammaincc(v/2, x/2), 1)
        i_nan = ((x == 0) & (v == 0)) | xp.isnan(x) | xp.isnan(v) | (v <= 0)
        res = xp.where(i_nan, xp.nan, res)
        return res
    return __chdtrc


def _betaincc(xp, spx):
    betainc = _get_native_func(xp, spx, 'betainc')  # noqa: F811
    if betainc is None:
        return None

    def __betaincc(a, b, x):
        # not perfect; might want to just rely on SciPy
        return betainc(b, a, 1-x)
    return __betaincc


def _stdtr(xp, spx):
    betainc = _get_native_func(xp, spx, 'betainc')  # noqa: F811
    if betainc is None:
        return None

    def __stdtr(df, t):
        x = df / (t ** 2 + df)
        tail = betainc(df / 2, 0.5, x) / 2
        return xp.where(t < 0, tail, 1 - tail)

    return __stdtr


def _stdtrit(xp, spx):
    betainc = _get_native_func(xp, spx, 'betainc')  # noqa: F811
    # If betainc is not defined, the root-finding would be done with `xp`
    # despite `stdtr` being evaluated with SciPy/NumPy `stdtr`. Save the
    # conversions: in this case, just evaluate `stdtrit` with SciPy/NumPy.
    if betainc is None:
        return None

    from scipy.optimize.elementwise import bracket_root, find_root

    def __stdtrit(df, p):
        def fun(t, df, p):  return stdtr(df, t) - p
        res_bracket = bracket_root(fun, xp.zeros_like(p), args=(df, p))
        res_root = find_root(fun, res_bracket.bracket, args=(df, p))
        return res_root.x

    return __stdtrit


_generic_implementations = {'rel_entr': _rel_entr,
                            'xlogy': _xlogy,
                            'chdtr': _chdtr,
                            'chdtrc': _chdtrc,
                            'betaincc': _betaincc,
                            'stdtr': _stdtr,
                            'stdtrit': _stdtrit,
                            }


# functools.wraps doesn't work because:
# 'numpy.ufunc' object has no attribute '__module__'
def support_alternative_backends(f_name):
    func = getattr(_ufuncs, f_name)

    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        xp = array_namespace(*args)
        f = get_array_special_func(f_name, xp)
        return f(*args, **kwargs)

    return wrapped


# function name: number of args (for testing purposes)
array_special_func_map = {
    'log_ndtr': 1,
    'ndtr': 1,
    'ndtri': 1,
    'erf': 1,
    'erfc': 1,
    'i0': 1,
    'i0e': 1,
    'i1': 1,
    'i1e': 1,
    'gammaln': 1,
    'gammainc': 2,
    'gammaincc': 2,
    'logit': 1,
    'expit': 1,
    'entr': 1,
    'rel_entr': 2,
    'xlogy': 2,
    'chdtr': 2,
    'chdtrc': 2,
    'betainc': 3,
    'betaincc': 3,
    'stdtr': 2,
    'stdtrit': 2,
}

globals().update(
    {f_name: support_alternative_backends(f_name)
     if SCIPY_ARRAY_API
     else getattr(_ufuncs, f_name)
     for f_name in array_special_func_map}
)

__all__ = list(array_special_func_map)

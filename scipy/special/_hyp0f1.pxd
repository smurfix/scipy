from libc.math cimport pow, sqrt, floor, log, log1p, exp, M_PI, NAN, fabs, isinf
cimport numpy as np

from ._complexstuff cimport (
    zsqrt, zpow, zabs, npy_cdouble_from_double_complex,
    double_complex_from_npy_cdouble)

cdef extern from "xsf_wrappers.h" nogil:
    double xsf_iv(double v, double x)
    double cephes_jv_wrap(double v, double x)
    double xsf_gamma(double x)
    double xsf_gammaln(double x)
    double xsf_gammasgn(double x)

cdef extern from "float.h":
    double DBL_MAX, DBL_MIN


cdef extern from "xsf_wrappers.h":
    np.npy_cdouble special_ccyl_bessel_i(double v, np.npy_cdouble z) nogil
    np.npy_cdouble special_ccyl_bessel_j(double v, np.npy_cdouble z) nogil
    double xsf_sinpi(double x) nogil
    double xsf_xlogy(double x, double y) nogil

cdef extern from "numpy/npy_math.h":
    double npy_creal(np.npy_cdouble z) nogil

#
# Real-valued kernel
#
cdef inline double _hyp0f1_real(double v, double z) noexcept nogil:
    cdef double arg, v1, arg_exp, bess_val

    # handle poles, zeros
    if v <= 0.0 and v == floor(v):
        return NAN
    if z == 0.0 and v != 0.0:
        return 1.0

    # both v and z small: truncate the Taylor series at O(z**2)
    if fabs(z) < 1e-6*(1.0 + fabs(v)):
        return 1.0 + z/v + z*z/(2.0*v*(v+1.0))

    if z > 0:
        arg = sqrt(z)
        arg_exp = xsf_xlogy(1.0-v, arg) + xsf_gammaln(v)
        bess_val = xsf_iv(v-1, 2.0*arg)

        if (arg_exp > log(DBL_MAX) or bess_val == 0 or   # overflow
            arg_exp < log(DBL_MIN) or isinf(bess_val)):  # underflow
            return _hyp0f1_asy(v, z)
        else:
            return exp(arg_exp) * xsf_gammasgn(v) * bess_val
    else:
        arg = sqrt(-z)
        return pow(arg, 1.0 - v) * xsf_gamma(v) * cephes_jv_wrap(v - 1, 2*arg)


cdef inline double _hyp0f1_asy(double v, double z) noexcept nogil:
    r"""Asymptotic expansion for I_{v-1}(2*sqrt(z)) * Gamma(v)
    for real $z > 0$ and $v\to +\infty$.

    Based off DLMF 10.41
    """
    cdef:
        double arg = sqrt(z)
        double v1 = fabs(v - 1)
        double x = 2.0 * arg / v1
        double p1 = sqrt(1.0 + x*x)
        double eta = p1 + log(x) - log1p(p1)
        double arg_exp_i, arg_exp_k
        double pp, p2, p4, p6, u1, u2, u3, u_corr_i, u_corr_k
        double result, gs

    arg_exp_i = -0.5*log(p1)
    arg_exp_i -= 0.5*log(2.0*M_PI*v1)
    arg_exp_i += xsf_gammaln(v)
    gs = xsf_gammasgn(v)

    arg_exp_k = arg_exp_i
    arg_exp_i += v1 * eta
    arg_exp_k -= v1 * eta

    # large-v asymptotic correction, DLMF 10.41.10
    pp = 1.0/p1
    p2 = pp*pp
    p4 = p2*p2
    p6 = p4*p2
    u1 = (3.0 - 5.0*p2) * pp / 24.0
    u2 = (81.0 - 462.0*p2 + 385.0*p4) * p2 / 1152.0
    u3 = (30375.0 - 369603.0*p2 + 765765.0*p4 - 425425.0*p6) * pp * p2 / 414720.0
    u_corr_i = 1.0 + u1/v1 + u2/(v1*v1) + u3/(v1*v1*v1)

    result = exp(arg_exp_i - xsf_xlogy(v1, arg)) * gs * u_corr_i
    if v - 1 < 0:
        # DLMF 10.27.2: I_{-v} = I_{v} + (2/pi) sin(pi*v) K_v
        u_corr_k = 1.0 - u1/v1 + u2/(v1*v1) - u3/(v1*v1*v1)
        result += exp(arg_exp_k + xsf_xlogy(v1, arg)) * gs * 2.0 * xsf_sinpi(v1) * u_corr_k

    return result


#
# Complex valued kernel
#
cdef inline double complex _hyp0f1_cmplx(double v, double complex z) noexcept nogil:
    cdef:
        np.npy_cdouble zz = npy_cdouble_from_double_complex(z)
        np.npy_cdouble r
        double complex arg, s
        double complex t1, t2

    # handle poles, zeros
    if v <= 0.0 and v == floor(v):
        return NAN
    if z.real == 0.0 and z.imag == 0.0 and v != 0.0:
        return 1.0

    # both v and z small: truncate the Taylor series at O(z**2)
    if zabs(z) < 1e-6*(1.0 + zabs(v)):
        # need to do computations in this order, for otherwise $v\approx -z \ll 1$
        # it can lose precision (as was reported for 32-bit linux, see gh-6365)
        t1 = 1.0 + z/v
        t2 = z*z / (2.0*v*(v+1.0))
        return t1 + t2

    if npy_creal(zz) > 0:
        arg = zsqrt(z)
        s = 2.0 * arg
        r = special_ccyl_bessel_i(v-1.0, npy_cdouble_from_double_complex(s))
    else:
        arg = zsqrt(-z)
        s = 2.0 * arg
        r = special_ccyl_bessel_j(v-1.0, npy_cdouble_from_double_complex(s))

    return double_complex_from_npy_cdouble(r) * xsf_gamma(v) * zpow(arg, 1.0 - v)

from pytest import fixture, mark
import numpy as np
from numpy.testing import assert_allclose
import scipy.sparse as sp
from .. import rand_matrix, rand_ket
from ..accel import (
    matrixify,
    realify,
    issparse,
    isket,
    isop,
    isbra,
    isherm,
    mul,
    dot,
    _dot_sparse,
    _par_dot_csr_matvec,
    vdot,
    rdot,
    ldmul,
    rdmul,
    outer,
    _kron_dense,
    _kron_dense_big,
    _kron_sparse,
    kron,
    kronpow,
    explt,
)


_SPARSE_FORMATS = ("csr", "bsr", "csc", "coo")
_TEST_SZ = 4


@fixture
def sparse_mat():
    return rand_matrix(_TEST_SZ, sparse=True, density=0.5)


@fixture
def ket():
    return rand_ket(_TEST_SZ)


@fixture
def test_objs():
    d = 5
    od1 = rand_matrix(d)
    od2 = rand_matrix(d)
    os1 = rand_matrix(d, sparse=True, density=0.5)
    os2 = rand_matrix(d, sparse=True, density=0.5)
    kd1 = rand_ket(d)
    kd2 = rand_ket(d)
    ld = np.random.randn(d) + 1.0j * np.random.randn(d)
    return od1, od2, os1, os2, kd1, kd2, ld


@fixture
def d1():
    return rand_matrix(3)


@fixture
def d2():
    return rand_matrix(3)


@fixture
def d3():
    return rand_matrix(3)


@fixture
def s1():
    return rand_matrix(3, sparse=True, density=0.5)


@fixture
def s2():
    return rand_matrix(3, sparse=True, density=0.5)


@fixture
def s1nnz():
    return rand_matrix(3, sparse=True, density=0.75)


class TestMatrixify:
    def test_matrixify(self):
        def foo(n):
            return np.random.randn(n, n)
        a = foo(2)
        assert not isinstance(a, np.matrix)

        @matrixify
        def foo(n):
            return np.random.randn(n, n)
        a = foo(2)
        assert isinstance(a, np.matrix)


class TestRealify:
    def test_realify(self):
        def foo(a, b):
            return a + 1j * b
        a = foo(1, 1e-15)
        assert a.real == 1
        assert a.imag == 1e-15

        @realify
        def foo(a, b):
            return a + 1j * b
        a = foo(1, 1e-15)
        assert a.real == 1
        assert a.imag == 0


class TestShapes:
    def test_sparse(self):
        x = np.matrix([[1], [0]])
        assert not issparse(x)
        x = sp.csr_matrix(x)
        assert issparse(x)

    def test_ket(self):
        x = np.matrix([[1], [0]])
        assert(isket(x))
        assert(not isbra(x))
        assert(not isop(x))
        x = sp.csr_matrix(x)
        assert(isket(x))
        assert(not isbra(x))
        assert(not isop(x))

    def test_bra(self):
        x = np.matrix([[1, 0]])
        assert(not isket(x))
        assert(isbra(x))
        assert(not isop(x))
        x = sp.csr_matrix(x)
        assert(not isket(x))
        assert(isbra(x))
        assert(not isop(x))

    def test_op(self):
        x = np.matrix([[1, 0], [0, 0]])
        assert(not isket(x))
        assert(not isbra(x))
        assert(isop(x))
        x = sp.csr_matrix(x)
        assert(not isket(x))
        assert(not isbra(x))
        assert(isop(x))

    def test_isherm(self):
        a = np.matrix([[1.0, 2.0 + 3.0j],
                       [2.0 - 3.0j, 1.0]])
        assert(isherm(a))
        a = np.matrix([[1.0, 2.0 - 3.0j],
                       [2.0 - 3.0j, 1.0]])
        assert(not isherm(a))

    def test_isherm_sparse(self):
        a = sp.csr_matrix([[1.0, 2.0 + 3.0j],
                           [2.0 - 3.0j, 1.0]])
        assert(isherm(a))
        a = sp.csr_matrix([[1.0, 2.0 - 3.0j],
                           [2.0 - 3.0j, 1.0]])
        assert(not isherm(a))


class TestMul:
    def test_mul_dense_same(self, test_objs):
        a, b, _, _, _, _, _ = test_objs
        ca = mul(a, b)
        assert isinstance(ca, np.matrix)
        cn = np.multiply(a, b)
        assert_allclose(ca, cn)

    def test_mul_broadcast(self, test_objs):
        a, _, _, _, b, _, _ = test_objs
        ca = mul(a, b)
        assert isinstance(ca, np.matrix)
        cn = np.multiply(a, b)
        assert_allclose(ca, cn)
        ca = mul(a.H, b)
        assert isinstance(ca, np.matrix)
        cn = np.multiply(a.H, b)
        assert_allclose(ca, cn)

    def test_mul_sparse(self, test_objs):
        _, _, a, b, _, _, _ = test_objs
        cq = mul(a, b)
        cn = a.A * b.A
        assert issparse(cq)
        assert_allclose(cq.A, cn)
        cq = mul(b.A, a)
        cn = b.A * a.A
        assert issparse(cq)
        assert_allclose(cq.A, cn)

    def test_mul_sparse_broadcast(self, test_objs):
        _, _, a, _, b, _, _ = test_objs
        ca = mul(a, b)
        cn = np.multiply(a.A, b)
        assert_allclose(ca.A, cn)
        ca = mul(a.H, b)
        cn = np.multiply(a.H.A, b)
        assert_allclose(ca.A, cn)


class TestDot:
    def test_dot_matrix(self, test_objs):
        a, b, _, _, _, _, _ = test_objs
        ca = dot(a, b)
        assert isinstance(ca, np.matrix)
        cn = a @ b
        assert_allclose(ca, cn)

    def test_dot_ket(self, test_objs):
        a, _, _, _, b, _, _ = test_objs
        ca = dot(a, b)
        assert isinstance(ca, np.matrix)
        cn = a @ b
        assert_allclose(ca, cn)

    def test_dot_sparse_sparse(self, test_objs):
        _, _, a, b, _, _, _ = test_objs
        cq = dot(a, b)
        cn = a @ b
        assert issparse(cq)
        assert_allclose(cq.A, cn.A)

    def test_dot_sparse_dense(self, test_objs):
        _, _, a, _, b, _, _ = test_objs
        cq = dot(a, b)
        cn = a @ b
        assert not issparse(cq)
        assert_allclose(cq.A, cn)

    def test_dot_sparse_dense_ket(self, test_objs):
        _, _, a, _, b, _, _ = test_objs
        cq = dot(a, b)
        cn = a @ b
        assert not issparse(cq)
        assert isket(cq)
        assert_allclose(cq.A, cn)

    def test_par_dot_csr_matvec(self, sparse_mat, ket):
        x = _par_dot_csr_matvec(sparse_mat, ket, 2)
        y = _dot_sparse(sparse_mat, ket)
        assert x.dtype == complex
        assert x.shape == (_TEST_SZ, 1)
        assert_allclose(x, y)


class TestAccelVdot:
    def test_accel_vdot(self, test_objs):
        _, _, _, _, a, b, _ = test_objs
        ca = vdot(a, b)
        cn = (a.H @ b)[0, 0]
        assert_allclose(ca, cn)


class TestAccelRdot:
    def test_accel_rdot(self, test_objs):
        _, _, _, _, a, b, _ = test_objs
        cq = rdot(a.H, b)
        cn = (a.H @ b)[0, 0]
        assert_allclose(cq, cn)


class TestFastDiagMul:
    def test_ldmul_small(self, test_objs):
        mat, _, _, _, _, _, vec = test_objs
        a = ldmul(vec, mat)
        b = np.diag(vec) @ mat
        assert isinstance(a, np.matrix)
        assert_allclose(a, b)

    def test_ldmul_large(self):
        vec = np.random.randn(501)
        mat = rand_matrix(501)
        a = ldmul(vec, mat)
        b = np.diag(vec) @ mat
        assert isinstance(a, np.matrix)
        assert_allclose(a, b)

    def test_ldmul_sparse(self, test_objs):
        _, _, mat, _, _, _, vec = test_objs
        assert issparse(mat)
        a = ldmul(vec, mat)
        b = np.diag(vec) @ mat.A
        assert issparse(a)
        assert_allclose(a.A, b)

    def test_rdmul_small(self, test_objs):
        mat, _, _, _, _, _, vec = test_objs
        a = rdmul(mat, vec)
        b = mat @ np.diag(vec)
        assert isinstance(a, np.matrix)
        assert_allclose(a, b)

    def test_rdmul_large(self):
        vec = np.random.randn(501)
        mat = rand_matrix(501)
        a = rdmul(mat, vec)
        b = mat @ np.diag(vec)
        assert isinstance(a, np.matrix)
        assert_allclose(a, b)

    def test_rdmul_sparse(self, test_objs):
        _, _, mat, _, _, _, vec = test_objs
        a = rdmul(mat, vec)
        b = mat.A @ np.diag(vec)
        assert issparse(a)
        assert_allclose(a.A, b)


class TestOuter:
    def test_outer_ket_ket(self, test_objs):
        _, _, _, _, a, b, _ = test_objs
        c = outer(a, b)
        assert isinstance(c, np.matrix)
        d = np.multiply(a, b.T)
        assert_allclose(c, d)

    def test_outer_ket_bra(self, test_objs):
        _, _, _, _, a, b, _ = test_objs
        c = outer(a, b.H)
        assert isinstance(c, np.matrix)
        d = np.multiply(a, b.H)
        assert_allclose(c, d)

    def test_outer_bra_ket(self, test_objs):
        _, _, _, _, a, b, _ = test_objs
        c = outer(a.H, b)
        assert isinstance(c, np.matrix)
        d = np.multiply(a.H.T, b.T)
        assert_allclose(c, d)

    def test_outer_bra_bra(self, test_objs):
        _, _, _, _, a, b, _ = test_objs
        c = outer(a.H, b.H)
        assert isinstance(c, np.matrix)
        d = np.multiply(a.H.T, b.H)
        assert_allclose(c, d)


class TestExplt:
    def test_small(self):
        l = np.random.randn(3)
        en = np.exp(-1.0j * l * 7)
        eq = explt(l, 7)
        assert_allclose(eq, en)


# --------------------------------------------------------------------------- #
# Kronecker (tensor) product tests                                            #
# --------------------------------------------------------------------------- #

class TestKron:
    @mark.parametrize("func", [_kron_dense, _kron_dense_big])
    def test_kron_dense(self, d1, d2, func):
        x = func(d1, d2)
        assert d1.shape == (3, 3)
        assert d2.shape == (3, 3)
        xn = np.kron(d1, d2)
        assert_allclose(x, xn)
        assert isinstance(x, np.matrix)

    def test_kron_multi_args(self, d1, d2, d3):
        assert_allclose(kron(d1), d1)
        assert_allclose(kron(d1, d2, d3),
                        np.kron(np.kron(d1, d2), d3))

    def test_kron_mixed_types(self, d1, s1):
        assert_allclose(kron(d1, s1).A,
                        (sp.kron(d1, s1, 'csr')).A)
        assert_allclose(kron(s1, s1).A,
                        (sp.kron(s1, s1, 'csr')).A)


class TestKronSparseFormats:
    def test_sparse_sparse_auto(self, s1):
        c = _kron_sparse(s1, s1)
        assert c.format == 'csr'

    def test_sparse_dense_auto(self, s1, d1):
        c = _kron_sparse(s1, d1)
        assert c.format == 'bsr'

    def test_dense_sparse_auto(self, s1, d1):
        c = _kron_sparse(d1, s1)
        assert c.format == 'csr'

    def test_sparse_sparsennz(self, s1, s1nnz):
        c = _kron_sparse(s1, s1nnz)
        assert c.format == 'csr'

    @mark.parametrize("stype", _SPARSE_FORMATS)
    def test_sparse_sparse_to_sformat(self, s1, stype):
        c = _kron_sparse(s1, s1, stype=stype)
        assert c.format == stype

    @mark.parametrize("stype", (None,) + _SPARSE_FORMATS)
    def test_many_args_dense_last(self, s1, s2, d1, stype):
        c = kron(s1, s2, d1, stype=stype)
        assert c.format == (stype if stype is not None else "bsr")

    @mark.parametrize("stype", (None,) + _SPARSE_FORMATS)
    def test_many_args_dense_not_last(self, s1, s2, d1, stype):
        c = kron(d1, s1, s2, stype=stype)
        assert c.format == (stype if stype is not None else "csr")
        c = kron(s1, d1, s2, stype=stype)
        assert c.format == (stype if stype is not None else "csr")

    @mark.parametrize("stype", (None,) + _SPARSE_FORMATS)
    def test_many_args_dense_last_coo_construct(self, s1, s2, d1, stype):
        c = kron(s1, s2, d1, stype=stype, coo_build=True)
        assert c.format == (stype if stype is not None else "csr")

    @mark.parametrize("stype", (None,) + _SPARSE_FORMATS)
    def test_many_args_dense_not_last_coo_construct(self, s1, s2, d1, stype):
        c = kron(s1, d1, s2, stype=stype, coo_build=True)
        assert c.format == (stype if stype is not None else "csr")
        c = kron(d1, s1, s2, stype=stype, coo_build=True)
        assert c.format == (stype if stype is not None else "csr")


class TestKronPow:
    def test_dense(self, d1):
        x = d1 & d1 & d1
        y = kronpow(d1, 3)
        assert_allclose(x, y)

    def test_sparse(self, s1):
        x = s1 & s1 & s1
        y = kronpow(s1, 3)
        assert_allclose(x.A, y.A)

    @mark.parametrize("stype", _SPARSE_FORMATS)
    def test_sparse_formats(self, stype, s1):
        x = s1 & s1 & s1
        y = kronpow(s1, 3, stype=stype)
        assert y.format == stype
        assert_allclose(x.A, y.A)

    @mark.parametrize("sformat_in", _SPARSE_FORMATS)
    @mark.parametrize("stype", (None,) + _SPARSE_FORMATS)
    def test_sparse_formats_coo_construct(self, sformat_in, stype, s1):
        s1 = s1.asformat(sformat_in)
        x = s1 & s1 & s1
        y = kronpow(s1, 3, stype=stype, coo_build=True)
        assert y.format == stype if stype is not None else "sformat_in"
        assert_allclose(x.A, y.A)

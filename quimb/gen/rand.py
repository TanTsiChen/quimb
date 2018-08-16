"""Functions for generating random quantum objects and states.
"""
from functools import wraps, lru_cache
import math
import os
from importlib.util import find_spec

import numpy as np
import scipy.sparse as sp
import numexpr as ne

from ..accel import rdmul, dot, matrixify, _NUM_THREAD_WORKERS, get_thread_pool
from ..core import qu, ptr, kron, nmlz, prod


def complex_array(x, y):
    """Efficient creation of complex array.
    """
    d = x.size

    dtype = 'complex64' if x.dtype == 'float32' else 'complex128'

    # XXX: numexpr3 will support complex64 natively
    if dtype == 'complex128' and d > 32768:
        z = ne.evaluate("complex(x, y)")
    else:
        z = np.empty(x.shape, dtype=dtype)
        z.real = x
        z.imag = y

    return z


# -------------------------------- RANDOMGEN -------------------------------- #
if (
    find_spec('randomgen') and
    os.environ.get('QUIMB_USE_RANDOMGEN', '').lower() not in {'false', 'off'}
):

    _RANDOM_GENS = []

    @lru_cache(2)
    def _get_randomgens(num_threads):
        """Cached generation of random number generators, enables
        ``random_seed_fn`` functionality and greater efficiency.
        """
        global _RANDOM_GENS

        num_gens = len(_RANDOM_GENS)
        if num_gens < num_threads:
            from randomgen import Xoroshiro128

            # add more generators if not enough
            for _ in range(num_threads - num_gens):
                _RANDOM_GENS.append(Xoroshiro128())

        return _RANDOM_GENS[:num_threads]

    def seed_rand(seed):
        # all RNGs inherit state from the first RNG of _get_randomgens
        _get_randomgens(1)[0].seed(seed)

    def randn(shape, dtype=float, scale=1.0, loc=0.0,
              num_threads=None, seed=None):
        """Fast multithreaded generation of random normally distributed data
        using ``randomgen``.

        Parameters
        ----------
        shape : tuple[int]
            The shape of the output random array.
        dtype : {'complex128', 'float64', 'complex64' 'float32'}, optional
            The data-type of the output array.
        scale : float, optional
            Scale the random distribution by this amount.
        loc : float, optional
            Shift the random distribution by this amount.
        num_threads : int, optional
            How many threads to use. If ``None``, decide automatically.
        """
        if seed is not None:
            seed_rand(seed)

        if isinstance(shape, int):
            d = shape
            shape = (shape,)
        else:
            d = prod(shape)

        if num_threads is None:
            # only multi-thread for big ``d``
            if d <= 32768:
                num_threads = 1
            else:
                num_threads = _NUM_THREAD_WORKERS

        rgs = _get_randomgens(num_threads)

        # sequential generation
        if num_threads <= 1:

            def create(d, dtype):
                out = np.empty(d, dtype)
                rgs[0].generator.standard_normal(out=out, dtype=dtype)
                return out

        # threaded generation
        else:
            pool = get_thread_pool()

            # copy state to all RGs and jump to ensure no overlap
            for rg in rgs[1:]:
                rg.state = rgs[0].state
                rgs[0].jump()

            gens = [thread_rg.generator for thread_rg in rgs]
            S = math.ceil(d / num_threads)

            def _fill(gen, out, dtype, first, last):
                gen.standard_normal(out=out[first:last], dtype=dtype)

            def create(d, dtype):
                out = np.empty(d, dtype)
                # submit thread work
                fs = [
                    pool.submit(_fill, gen, out, dtype, i * S, (i + 1) * S)
                    for i, gen in enumerate(gens)
                ]
                # wait for completion
                [f.result() for f in fs]
                return out

        if np.issubdtype(dtype, np.floating):
            out = create(d, dtype)

        elif np.issubdtype(dtype, np.complexfloating):
            # need to sum two real arrays if generating complex numbers
            if np.issubdtype(dtype, np.complex64):
                sub_dtype = np.float32
            else:
                sub_dtype = np.float64

            out = complex_array(create(d, sub_dtype), create(d, sub_dtype))

        else:
            raise ValueError("dtype {} not understood.".format(dtype))

        if out.dtype != dtype:
            out = out.astype(dtype)

        if scale != 1.0:
            out *= scale
        if loc != 0.0:
            out += loc

        return out.reshape(shape)

    def rand(*args, **kwargs):
        return _get_randomgens(1)[0].generator.rand(*args, **kwargs)

    def randint(*args, **kwargs):
        return _get_randomgens(1)[0].generator.randint(*args, **kwargs)

    def choice(*args, **kwargs):
        return _get_randomgens(1)[0].generator.choice(*args, **kwargs)

# ---------------------------------- NUMPY ---------------------------------- #
else:

    def seed_rand(seed):
        np.random.seed(seed)

    def randn(shape, loc=0.0, scale=1.0, dtype=float, seed=None):
        """Generate normally distributed random array of certain shape and type.
        Like :func:`numpy.random.randn` but can specify ``dtype``.

        Parameters
        ----------
        shape : tuple[int]
            The shape of the array.
        dtype : {float, complex, ...}, optional
            The numpy data type.

        Returns
        -------
        A : array
        """
        if seed is not None:
            seed_rand(seed)

        # real datatypes
        if np.issubdtype(dtype, np.floating):
            x = np.random.normal(loc=loc, scale=scale, size=shape)

        # complex datatypes
        elif np.issubdtype(dtype, np.complexfloating):
            x = complex_array(
                np.random.normal(loc=loc, scale=scale, size=shape),
                np.random.normal(loc=loc, scale=scale, size=shape),
            )
        else:
            raise TypeError("dtype {} not understood - should be float or "
                            "complex.".format(dtype))

        if x.dtype != dtype:
            x = x.astype(dtype)

        return x

    choice = np.random.choice
    randint = np.random.randint
    rand = np.random.rand


def random_seed_fn(fn):
    """Modify ``fn`` to take a ``seed`` argument.
    """

    @wraps(fn)
    def wrapped_fn(*args, seed=None, **kwargs):
        if seed is not None:
            seed_rand(seed)
        return fn(*args, **kwargs)

    return wrapped_fn


@random_seed_fn
def rand_rademacher(shape, scale=1, dtype=float):
    """
    """
    if np.issubdtype(dtype, np.floating):
        entries = np.array([1.0, -1.0]) * scale
        need2convert = dtype not in (float, np.float_)

    elif np.issubdtype(dtype, np.complexfloating):
        entries = np.array([1.0, -1.0, 1.0j, -1.0j]) * scale
        need2convert = dtype not in (complex, np.complex_)

    else:
        raise TypeError("dtype {} not understood - should be float or complex."
                        "".format(dtype))

    x = choice(entries, shape)
    if need2convert:
        x = x.astype(dtype)

    return x


@random_seed_fn
def rand_matrix(d, scaled=True, sparse=False, stype='csr',
                density=None, dtype=complex):
    """Generate a random complex matrix of order `d` with normally distributed
    entries. If `scaled` is `True`, then in the limit of large `d` the
    eigenvalues will be distributed on the unit complex disk.

    Parameters
    ----------
    d : int
        Matrix dimension.
    scaled : bool, optional
        Whether to scale the matrices values such that its spectrum
        approximately lies on the unit disk (for dense matrices).
    sparse : bool, optional
        Whether to produce a sparse matrix.
    stype : {'csr', 'csc', 'coo', ...}, optional
        The type of sparse matrix if ``sparse=True``.
    density : float, optional
        Target density of non-zero elements for the sparse matrix.
    dtype : {complex, float}, optional
        The data type of the matrix elements.

    Returns
    -------
        mat: random matrix
    """
    if np.issubdtype(dtype, np.floating):
        iscomplex = False
    elif np.issubdtype(dtype, np.complexfloating):
        iscomplex = True
    else:
        raise TypeError("dtype {} not understood - should be "
                        "float or complex.".format(dtype))

    if sparse:
        # Aim for 10 non-zero values per row, but betwen 1 and d/2
        density = 10 / d if density is None else density
        density = min(max(density, d**-2), 1 - d**-2)

        mat = sp.random(d, d, format=stype, density=density)
        nnz = mat.nnz

        mat.data = randn(nnz, dtype=dtype)

    else:
        density = 1.0
        mat = np.asmatrix(randn((d, d), dtype=dtype))

    if scaled:
        mat /= ((2 if iscomplex else 1) * d * density)**0.5

    return mat


@random_seed_fn
def rand_herm(d, sparse=False, density=None, dtype=complex):
    """Generate a random hermitian matrix of order `d` with normally
    distributed entries. In the limit of large `d` the spectrum will be a
    semi-circular distribution between [-1, 1].

    See Also
    --------
    rand_matrix, rand_pos, rand_rho, rand_uni
    """
    if sparse:
        density = 10 / d if density is None else density
        density = min(max(density, d**-2), 1 - d**-2)
        density /= 2  # to account of herm construction

    herm = rand_matrix(d, scaled=True, sparse=sparse,
                       density=density, dtype=dtype)

    if sparse:
        herm.data /= (2**1.5)
    else:
        herm /= (2**1.5)

    herm += herm.H

    return herm


@random_seed_fn
def rand_pos(d, sparse=False, density=None, dtype=complex):
    """Generate a random positive matrix of order `d`, with normally
    distributed entries. In the limit of large `d` the spectrum will lie
    between [0, 1].

    See Also
    --------
    rand_matrix, rand_herm, rand_rho, rand_uni
    """
    if sparse:
        density = 10 / d if density is None else density
        density = min(max(density, d**-2), 1 - d**-2)
        density = 0.5 * (density / d)**0.5  # to account for pos construction

    pos = rand_matrix(d, scaled=True, sparse=sparse,
                      density=density, dtype=dtype)

    return dot(pos, pos.H)


@random_seed_fn
def rand_rho(d, sparse=False, density=None, dtype=complex):
    """Generate a random positive matrix of order `d` with normally
    distributed entries and unit trace.

    See Also
    --------
    rand_matrix, rand_herm, rand_pos, rand_uni
    """
    return nmlz(rand_pos(d, sparse=sparse, density=density, dtype=dtype))


@random_seed_fn
def rand_uni(d, dtype=complex):
    """Generate a random unitary matrix of order `d`, distributed according to
    the Haar measure.

    See Also
    --------
    rand_matrix, rand_herm, rand_pos, rand_rho
    """
    q, r = np.linalg.qr(rand_matrix(d, dtype=dtype))
    r = np.diagonal(r)
    r = r / np.abs(r)
    return rdmul(q, r)


@random_seed_fn
def rand_ket(d, sparse=False, stype='csr', density=0.01, dtype=complex):
    """Generates a ket of length `d` with normally distributed entries.
    """
    if sparse:
        ket = sp.random(d, 1, format=stype, density=density)
        ket.data = randn((ket.nnz,), dtype=dtype)
    else:
        ket = np.asmatrix(randn((d, 1), dtype=dtype))
    return nmlz(ket)


@random_seed_fn
def rand_haar_state(d):
    """Generate a random state of dimension `d` according to the Haar
    distribution.
    """
    u = rand_uni(d)
    return u[:, 0]


@random_seed_fn
def gen_rand_haar_states(d, reps):
    """Generate many random Haar states, recycling a random unitary matrix
    by using all of its columns (not a good idea?).
    """
    for rep in range(reps):
        cyc = rep % d
        if cyc == 0:
            u = rand_uni(d)
        yield u[:, cyc]


@random_seed_fn
def rand_mix(d, tr_d_min=None, tr_d_max=None, mode='rand'):
    """Constructs a random mixed state by tracing out a random ket
    where the composite system varies in size between 2 and d. This produces
    a spread of states including more purity but has no real meaning.
    """
    if tr_d_min is None:
        tr_d_min = 2
    if tr_d_max is None:
        tr_d_max = d

    m = randint(tr_d_min, tr_d_max)
    if mode == 'rand':
        psi = rand_ket(d * m)
    elif mode == 'haar':
        psi = rand_haar_state(d * m)

    return ptr(psi, [d, m], 0)


@random_seed_fn
def rand_product_state(n, qtype=None):
    """Generates a ket of `n` many random pure qubits.
    """
    def gen_rand_pure_qubits(n):
        for _ in range(n):
            u = rand()
            v = rand()
            phi = 2 * np.pi * u
            theta = np.arccos(2 * v - 1)
            yield qu([[np.cos(theta / 2.0)],
                      [np.sin(theta / 2.0) * np.exp(1.0j * phi)]],
                     qtype=qtype)
    return kron(*gen_rand_pure_qubits(n))


@matrixify
@random_seed_fn
def rand_matrix_product_state(n, bond_dim, phys_dim=2, dtype=complex,
                              cyclic=False, trans_invar=False):
    """Generate a random matrix product state (in dense form, see
    :func:`~quimb.tensor.MPS_rand_state` for tensor network form).

    Parameters
    ----------
    n : int
        Number of sites.
    bond_dim : int
        Dimension of the bond (virtual) indices.
    phys_dim : int, optional
        Physical dimension of each local site, defaults to 2 (qubits).
    cyclic : bool (optional)
        Whether to impose cyclic boundary conditions on the entanglement
        structure.
    trans_invar : bool (optional)
        Whether to generate a translationally invariant state,
        requires cyclic=True.

    Returns
    -------
    ket : matrix-like
        The random state, with shape (phys_dim**n, 1)

    """
    from quimb.tensor import MPS_rand_state

    mps = MPS_rand_state(n, bond_dim, phys_dim=phys_dim, dtype=dtype,
                         cyclic=cyclic, trans_invar=trans_invar)
    return mps.to_dense()


rand_mps = rand_matrix_product_state


@random_seed_fn
def rand_seperable(dims, num_mix=10):
    """Generate a random, mixed, seperable state. E.g rand_seperable([2, 2])
    for a mixed two qubit state with no entanglement.

    Parameters
    ----------
        dims : tuple of int
            The local dimensions across which to be seperable.
        num_mix : int, optional
            How many individual product states to sum together, each with
            random weight.

    Returns
    -------
        np.matrix
            Mixed seperable state.
    """

    def gen_single_sites():
        for dim in dims:
            yield rand_rho(dim)

    weights = rand(num_mix)

    def gen_single_states():
        for w in weights:
            yield w * kron(*gen_single_sites())

    return sum(gen_single_states()) / np.sum(weights)


@random_seed_fn
def rand_iso(n, m, dtype=complex):
    """Generate a random isometry of shape ``(n, m)``.
    """
    data = randn((n, m), dtype=dtype)

    q, _ = np.linalg.qr(data if n > m else data.T)
    q = q.astype(dtype)

    return q if (n > m) else q.T


@random_seed_fn
def rand_mera(n, invariant=False, dtype=complex):
    """Generate a random mera state of ``n`` qubits, which must be a power
    of 2. This uses ``quimb.tensor``.
    """
    import quimb.tensor as qt

    if invariant:
        constructor = qt.MERA.rand_invar
    else:
        constructor = qt.MERA.rand

    return constructor(n, dtype=dtype).to_dense()

"""The declared RNG of a World transition and the refusal of every other (T3-006).

K0 owns the seed tree (``kernel/seed.py``): one transition has one bound world
seed, derived from the plan's root seed by its episode, round and transition.
Under a World contract (``bvl-world-contract-4``, ``kernel/world.py``) that seed
is the only randomness a transition may have, and it reaches a World in exactly
one of two ways:

    DETERMINISTIC  ``apply(state, action, *, seed)``.  The seed is handed for the
                   K0 entry point's sake and must not change the transition: the
                   replays hand another seed (``probe_seed``) and must state the
                   same transition.
    SEEDED         ``apply(state, action, *, rng)``.  ``rng`` is a ``WorldRng``:
                   the ``bvl-rng-sha256-ctr-1`` stream of the bound seed, whose
                   draws are counted and evidenced.  The World is never handed
                   the seed, and the RNG is closed when ``apply`` returns.

``bvl-rng-sha256-ctr-1`` is defined on bytes, so a stream is the same on every
platform and Python:

    key      = SHA-256(canonical {"schema": "bvl-rng-sha256-ctr-1", "seed": seed})
    block i  = SHA-256(key || i as 8 big-endian bytes),  i = 0, 1, ...
    stream   = block 0 || block 1 || ...
    randbits(k)   the next ceil(k / 8) bytes, big-endian, shifted right to k bits
    randbelow(n)  0 for n = 1; else randbits((n - 1).bit_length()) redrawn until below n

Hidden plugin RNG is every other source.  ``hidden_rng_refused`` holds the
standard ones shut for the duration of one ``World.apply`` and refuses a
transition that reached one (BVL-WORLD-013), whatever the World then stated.
The purity replay holds every other pure plugin - renderer, visibility
transform, provider codec, proposal parser, decision rule - shut the same way
(SV-05; refused as IMPURE_PLUGIN):

    the process generator    ``random.random()``, ``random.randint()``, ... - for
                             the call it is put in a state of the kernel's own
                             choosing and must be found in it afterwards; the
                             process's state is then restored (NumPy's legacy
                             global generator, when loaded, is compared before
                             and after)
    an unseeded generator    ``random.Random()``, ``random.seed()``
    OS entropy               ``os.urandom``, ``random.SystemRandom``, ``secrets``,
                             ``uuid.uuid4``

A generator a World seeds itself with a constant is a deterministic function and
is not refused; one it keys by draws from the declared RNG is declared
randomness.  What no in-process guard sees - the clock, object addresses, a
native library's own generator, a World that saves and restores the process
generator's state - is left to the replay (BVL-WORLD-009).
"""

from __future__ import annotations

import inspect
import os
import random
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from boomvalley_lab.core.digest import sha256_bytes, sha256_document
from boomvalley_lab.core.errors import ExecutionError
from boomvalley_lab.kernel.world import (
    RNG,
    RNG_ALGORITHM,
    RNG_POLICY_INVALID,
    WorldRngPolicyV1,
)

_MAX_BITS = 1 << 16
#: where the process generator is parked while a World is applied: a state no
#: World chose, advanced on every call
_PARKED = random.Random(0x62766C2D776F726C642D726E672D31)


def _refusal(detail: str) -> ExecutionError:
    return ExecutionError(f"{RNG_POLICY_INVALID}: {detail}", code=RNG_POLICY_INVALID)


class WorldRng:
    """The declared RNG of one transition: the ``bvl-rng-sha256-ctr-1`` stream of its seed."""

    algorithm = RNG_ALGORITHM

    def __init__(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("a world seed is a non-negative integer")
        # only the key is kept: the seed itself is not recoverable from the RNG
        self._key = bytes.fromhex(sha256_document({"schema": RNG_ALGORITHM, "seed": seed}).hex)
        self._block = 0
        self._buffer = b""
        self._draws = 0
        self._bits = 0
        self._closed = False

    @property
    def draws(self) -> int:
        """How many times the stream was drawn from."""

        return self._draws

    @property
    def bits(self) -> int:
        """How many bits those draws returned."""

        return self._bits

    def close(self) -> None:
        """End the transition's stream: a World that kept the RNG draws nothing more."""

        self._closed = True

    def __reduce__(self) -> Any:  # neither copied nor pickled: it is one transition's
        raise TypeError("the declared RNG of a transition is not copied or kept")

    def _take(self, count: int) -> bytes:
        while len(self._buffer) < count:
            block = sha256_bytes(self._key + self._block.to_bytes(8, "big")).hex
            self._buffer += bytes.fromhex(block)
            self._block += 1
        taken, self._buffer = self._buffer[:count], self._buffer[count:]
        return taken

    def randbits(self, k: int) -> int:
        """An integer of *k* uniformly random bits (1 <= k <= 65536)."""

        if self._closed:
            raise _refusal(
                "the declared RNG was drawn from after its transition's apply returned"
            )
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= _MAX_BITS:
            raise ValueError(f"randbits draws 1..{_MAX_BITS} bits")
        size = (k + 7) // 8
        self._draws += 1
        self._bits += k
        return int.from_bytes(self._take(size), "big") >> (size * 8 - k)

    def randbelow(self, n: int) -> int:
        """A uniformly random integer in ``[0, n)``."""

        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError("randbelow draws below an integer >= 1")
        if n == 1:
            return 0
        k = (n - 1).bit_length()
        drawn = self.randbits(k)
        while drawn >= n:
            drawn = self.randbits(k)
        return drawn

    def random(self) -> float:
        """A uniformly random float in ``[0.0, 1.0)`` of 53 random bits."""

        return self.randbits(53) / (1 << 53)

    def choice(self, items: Sequence[Any]) -> Any:
        """One uniformly random item of a non-empty sequence."""

        if not items:
            raise ValueError("choice draws from a non-empty sequence")
        return items[self.randbelow(len(items))]

    def shuffled(self, items: Sequence[Any]) -> list[Any]:
        """A uniformly random permutation of *items* (Fisher-Yates), as a new list."""

        made = list(items)
        for index in range(len(made) - 1, 0, -1):
            other = self.randbelow(index + 1)
            made[index], made[other] = made[other], made[index]
        return made


def probe_seed(seed: int, probe: str) -> int:
    """Another seed than *seed*: what a DETERMINISTIC World is replayed under."""

    digest = sha256_document({"schema": RNG, "seed": seed, "probe": probe})
    other = int(digest.hex[:16], 16) & ((1 << 63) - 1)
    return other if other != seed else other ^ 1


def entry_point_problems(world: Any, policy: WorldRngPolicyV1) -> list[str]:
    """Why ``world.apply`` is not the entry point of *policy* (BVL-WORLD-013)."""

    try:
        parameters = inspect.signature(world.apply).parameters
    except (TypeError, ValueError):
        return []  # a callable without a signature is held to its policy when called
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return ["apply accepts arbitrary keywords: it does not state whether it is handed "
                "a seed or the declared RNG"]
    takes_rng, takes_seed = "rng" in parameters, "seed" in parameters
    if policy.seeded and (not takes_rng or takes_seed):
        return ["a SEEDED World's entry point is apply(state, action, *, rng): it is handed "
                "the declared RNG and never a seed"]
    if not policy.seeded and takes_rng:
        return ["apply takes an rng, but the World declares no SEEDED rng policy"]
    return []


def _numpy_state() -> Any:
    module = sys.modules.get("numpy.random")
    if module is None:
        return None
    try:
        name, keys, *rest = module.get_state()
        return (name, keys.tobytes(), tuple(rest))
    except Exception:  # noqa: BLE001 - a NumPy without the legacy generator has no state
        return None


@contextmanager
def hidden_rng_refused(world: str, *, kind: str = "World") -> Iterator[None]:
    """Hold hidden plugin RNG shut for one ``World.apply`` (BVL-WORLD-013).

    A reach is recorded before it is refused, so a World that swallows the
    refusal - or only advances the process generator - is still refused when
    its ``apply`` returns.  *kind* names what was called when it is not a World:
    the purity replay holds every other pure plugin the same way (SV-05,
    ``containment.invoke_pure``), and such a plugin has no declared RNG at all.
    """

    reached: list[str] = []

    def refuse(source: str) -> None:
        reached.append(source)
        raise _refusal(f"{kind} {world!r} reached hidden plugin RNG: {source}")

    seed = random.Random.seed
    urandom, module_urandom = os.urandom, random._urandom  # noqa: SLF001

    def guarded_seed(self: random.Random, a: Any = None, version: int = 2) -> None:
        if a is None:
            refuse("an unseeded random generator (random.Random() / random.seed())")
        seed(self, a, version)

    def guarded_urandom(size: int) -> bytes:
        refuse("OS entropy (os.urandom / SystemRandom / secrets / uuid4)")
        return b""  # unreachable

    process, numpy = random.getstate(), _numpy_state()
    _PARKED.random()
    parked = _PARKED.getstate()
    random.setstate(parked)
    random.Random.seed = guarded_seed  # type: ignore[method-assign]
    os.urandom = random._urandom = guarded_urandom  # type: ignore[assignment]  # noqa: SLF001
    try:
        yield
    finally:
        random.Random.seed = seed  # type: ignore[method-assign]
        os.urandom, random._urandom = urandom, module_urandom  # noqa: SLF001
        moved = random.getstate() != parked
        random.setstate(process)  # the process generator is left as it was found
    if moved:
        reached.append("the process random generator (random.random(), random.randint(), ...)")
    if _numpy_state() != numpy:
        reached.append("NumPy's global random generator (numpy.random.*)")
    if reached:
        raise _refusal(
            f"{kind} {world!r} reached hidden plugin RNG: {'; '.join(dict.fromkeys(reached))}; "
            + ("the only randomness of a transition is the declared RNG of its bound seed"
               if kind == "World" else "a pure plugin has no randomness of its own")
        )


def apply_under_policy(
    world: Any,
    policy: WorldRngPolicyV1,
    state: Mapping[str, Any],
    action: Mapping[str, Any] | None,
    *,
    seed: int,
    probe: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """One ``World.apply`` under *policy*: what it returned and its RNG evidence.

    A SEEDED World is handed a fresh ``WorldRng`` of *seed*; a DETERMINISTIC
    one the seed, or with *probe* another seed its transition must not notice.
    """

    identity = str(getattr(world, "plugin_identity", type(world).__qualname__))
    unfit = entry_point_problems(world, policy)
    if unfit:
        raise _refusal(f"World {identity!r}: {'; '.join(unfit)}")
    if not policy.seeded:
        handed = seed if probe is None else probe_seed(seed, probe)
        with hidden_rng_refused(identity):
            made = world.apply(state, action, seed=handed)
        return made, policy.evidence()
    rng = WorldRng(seed)
    try:
        with hidden_rng_refused(identity):
            made = world.apply(state, action, rng=rng)
    finally:
        rng.close()
    return made, policy.evidence(draws=rng.draws, bits=rng.bits)


def stream_digest(seed: int, size: int = 64) -> str:
    """The digest of the first *size* bytes of a seed's stream (a conformance vector)."""

    return sha256_bytes(WorldRng(seed)._take(size)).hex  # noqa: SLF001


__all__ = [
    "WorldRng",
    "apply_under_policy",
    "entry_point_problems",
    "hidden_rng_refused",
    "probe_seed",
    "stream_digest",
]

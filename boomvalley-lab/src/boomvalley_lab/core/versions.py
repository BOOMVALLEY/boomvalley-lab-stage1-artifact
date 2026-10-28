"""Version identifiers, independent of each other.

Each names one contract a reader of an evidence package (FULLMT included) must
know in order to recompute what the package claims. They change independently:
a new package layout does not change how a document is canonicalised, and a new
canonical format does not change the digest algorithm.
"""

from __future__ import annotations

#: The Python distribution / product version.
PACKAGE_VERSION = "1.0.0rc3"

#: The evidence-package schema (the future `PACKAGE.json` layout).
PACKAGE_SCHEMA_VERSION = "boomvalley-lab-package-1"

#: How a document becomes bytes. See `core.canonical`.
CANONICAL_FORMAT = "canonical-json-1"

#: How bytes become a digest. See `core.digest`.
DIGEST_ALGORITHM = "sha256"

#: How identities are formed: CANONICAL_FORMAT bytes digested by DIGEST_ALGORITHM.
IDENTITY_SCHEME = f"{DIGEST_ALGORITHM}/{CANONICAL_FORMAT}"


def version_document() -> dict[str, str]:
    """The versions a package must record so its identities can be recomputed."""
    return {
        "package_version": PACKAGE_VERSION,
        "package_schema": PACKAGE_SCHEMA_VERSION,
        "canonical_format": CANONICAL_FORMAT,
        "digest_algorithm": DIGEST_ALGORITHM,
        "identity_scheme": IDENTITY_SCHEME,
    }

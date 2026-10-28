"""Foundation shared by every other package. Depends on nothing in the product.

    canonical   the one canonical-document serializer and its omission rule
    strict_json the one reader of JSON read back: one document, one meaning
    digest      the one digest service (SHA-256); no other module calls hashlib
    verdict     the three-state verification verdict
    errors      the error categories the CLI distinguishes
    versions    independent version identifiers for package, format, identity
"""

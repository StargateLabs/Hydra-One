"""Recovered H1v2: verified CPU embeddings with reciprocal lexical/dense fusion.

This reconstruction has a new identity; historical H1v2 quality is not attested.
"""
from .graph_hybrid import HybridLab


class HybridLabV2(HybridLab):
    fusion = True

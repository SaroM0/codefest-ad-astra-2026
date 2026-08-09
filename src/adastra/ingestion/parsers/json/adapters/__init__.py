"""Adapters por familia de esquema JSON.

No se desarrolla un extractor universal: las familias del corpus son conocidas y
enumerables. Un extractor genérico sobre esquemas conocidos añade no-determinismo sin
aportar cobertura.
"""

from .articles import ArticleAdapter
from .alerts import AlertasAdapter
from .cenia import CENIAAdapter
from .journal import JournalAdapter

__all__ = ["ArticleAdapter", "AlertasAdapter", "CENIAAdapter", "JournalAdapter"]

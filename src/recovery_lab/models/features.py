"""Feature matrices built strictly from the registry (leakage guard enforced there)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

from ..config import Config
from ..data.registry import Registry


class FeatureBuilder:
    """Fit on training rows, transform any rows. Categories are frozen at fit time."""

    def __init__(self, cfg: Config, reg: Registry, model: str, n_text: int | None = None):
        self.model = model
        f = reg.features(model)
        self.num, self.cat, self.txt, self.boo = f["numeric"], f["categorical"], f["text"], f["boolean"]
        self.n_text = n_text if n_text is not None else cfg.model("recovery").get("text_svd_components", 8)
        self.cats: dict = {}
        self.tfidf = self.svd = None

    @property
    def names(self) -> list:
        t = [f"title_svd_{i}" for i in range(self.n_text)] if self.txt else []
        return self.num + self.cat + self.boo + t

    def fit(self, df: pd.DataFrame) -> "FeatureBuilder":
        for c in self.cat:
            self.cats[c] = sorted(df[c].astype(str).unique())
        if self.txt:
            self.tfidf = TfidfVectorizer(min_df=5, ngram_range=(1, 2), max_features=4000)
            X = self.tfidf.fit_transform(df[self.txt[0]].fillna(""))
            k = max(1, min(self.n_text, X.shape[1] - 1))
            self.svd = TruncatedSVD(k, random_state=0).fit(X)
            self.n_text = k
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[self.num].astype(float).copy()
        for c in self.cat:
            X[c] = pd.Categorical(df[c].astype(str), categories=self.cats[c])
        for b in self.boo:
            X[b] = df[b].astype(float)
        if self.txt:
            Z = self.svd.transform(self.tfidf.transform(df[self.txt[0]].fillna("")))
            for i in range(Z.shape[1]):
                X[f"title_svd_{i}"] = Z[:, i]
        X.index = df.index
        return X[self.names]

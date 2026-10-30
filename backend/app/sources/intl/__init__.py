"""Importers for national food composition databases outside the U.S.

Each module exposes ``parse(files: dict[str, Path]) -> Iterator[ExternalFood]`` where
``files`` maps the names declared for its dataset in ``app.services.datasets`` to the
downloaded files. Shared value parsing and nutrient-definition handling live in
``common``; see the notes there on what is (and deliberately isn't) mapped.
"""

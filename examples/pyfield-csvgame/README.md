# pyfield-csvgame — reference third-party adapter

Install next to PyField and the adapter is discovered automatically:

```powershell
pip install ./examples/pyfield-csvgame
python -c "import pyfield; print(pyfield.games.get('csvgame'))"
pyfield capabilities csvgame
```

Use it as the template for a new game package: copy, rename the package and entry point,
replace the FormatSpec/HeaderScheme/GroupLayout, and ship schemas with their own
`SCHEMA_VERSION`. See `../../docs/adapters.md`.

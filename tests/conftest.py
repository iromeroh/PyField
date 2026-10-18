def pytest_configure(config):
    config.addinivalue_line('markers', 'corpus: needs installed game data (PYFIELD_STARFIELD_DATA / PYFIELD_OBLIVION_DATA)')
    config.addinivalue_line('markers', 'slow: reads very large masters')

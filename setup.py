"""Setup for tubular"""
from setuptools import setup

setup(
    # Pinned below 7.0: pbr>=7.0 drops Python 3.8 support, and constraints.txt
    # alone isn't respected for setup_requires. Remove once agents are on Python 3.11+.
    setup_requires=[u'pbr>=1.9,<7.0', u'setuptools>=17.1'],
    python_requires=">=3.6, <3.9",
    pbr=True,
)

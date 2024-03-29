#! /usr/bin/env python3

from setuptools import setup

setup(
    name="emaillib",
    use_scm_version=True,
    setup_requires=["setuptools_scm"],
    author="HOMEINFO - Digitale Informationssysteme GmbH",
    author_email="<info@homeinfo.de>",
    maintainer="Richard Neumann",
    maintainer_email="<r.neumann@homeinfo.de>",
    py_modules=["emaillib"],
    license="GPLv3",
    description="An enhanced emailing library.",
)

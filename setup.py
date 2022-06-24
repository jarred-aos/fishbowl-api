from setuptools import setup
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="fishbowl-api",
    version="1.6.2",
    description="Fishbowl API",
    long_description=long_description,
    url="http://github.com/patriotresearch/fishbowl-api",
    author="chipolux",
    author_email="nwright@atlaswhd.com",
    license="MIT",
    packages=["fishbowl"],
    install_requires=["lxml"],
)

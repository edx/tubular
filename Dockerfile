FROM ubuntu:focal AS base


ARG PYTHON_VERSION=3.11


# software-properties-common is needed to setup our Python 3.11 env
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    apt-add-repository -y ppa:deadsnakes/ppa


# System requirements
# - build-essential; meta-package that install a collection of essential tools for compiling software from source (e.g. gcc, g++, make, etc.)
# - language-pack-en & locales; Ubuntu locale support so that system utilities have a consistent language and time zone.
# - python${PYTHON_VERSION}; Ubuntu doesn't ship with Python, this is the Python version used to run the application
# - python${PYTHON_VERSION}-dev; to install header files for python extensions, wheel-building depends on this
#
# If you add a package here please include a comment above describing what it is used for
RUN apt-get update && apt-get -qy install --no-install-recommends \
        build-essential \
        curl \
        language-pack-en \
        locales \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-dev

# need to use virtualenv pypi package with Python 3.11
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python${PYTHON_VERSION}
RUN pip install virtualenv
# create our Python virtual env
ENV VIRTUAL_ENV=/edx/venvs/credentials
RUN virtualenv -p python$PYTHON_VERSION $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app
ADD . /app

RUN pip install -r requirements.txt

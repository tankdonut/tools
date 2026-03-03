ARG PYTHON_VERSION="3.14.2"

FROM docker.io/library/python:${PYTHON_VERSION}-alpine as build

# hadolint ignore=DL3018
RUN apk add --update --no-cache bash coreutils curl git tar xz

COPY . /tools

WORKDIR /tools

RUN pip install --no-cache-dir uv=="$(awk '/^uv/ {print $2}' .tool-versions)"

# hadolint ignore=DL3059
RUN uv run invoke install

WORKDIR /tools/dist

FROM scratch

COPY --from=build /tools/dist /dist

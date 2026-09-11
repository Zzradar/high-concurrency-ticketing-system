FROM ubuntu:24.04 AS build

ARG DEBIAN_FRONTEND=noninteractive
ARG UBUNTU_MIRROR=""

RUN set -- \
    && if [ -n "$UBUNTU_MIRROR" ]; then \
        test -f /etc/apt/sources.list.d/ubuntu.sources \
        && sed -i -E "s#https?://(archive|security)\.ubuntu\.com/ubuntu/?#${UBUNTU_MIRROR%/}#g" /etc/apt/sources.list.d/ubuntu.sources \
        && set -- -o Acquire::http::Proxy=DIRECT -o Acquire::https::Proxy=DIRECT; \
    fi \
    && apt-get "$@" update \
    && apt-get "$@" install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        libbrotli-dev \
        libargon2-dev \
        libc-ares-dev \
        libjsoncpp-dev \
        libhiredis-dev \
        libpq-dev \
        libssl-dev \
        python3 \
        uuid-dev \
        zlib1g-dev \
    && test -s /etc/ssl/certs/ca-certificates.crt \
    && case "$UBUNTU_MIRROR" in \
        http://*) mirror_pattern=$(printf '%s' "${UBUNTU_MIRROR%/}" | sed 's/[][\\.^$*#]/\\&/g') \
            && sed -i "s#${mirror_pattern}#https://${UBUNTU_MIRROR#http://}#g" /etc/apt/sources.list.d/ubuntu.sources ;; \
    esac \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . .

RUN cmake -S . -B build \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_TESTING=ON \
        -DBUILD_SHARED_LIBS=OFF \
        -DTICKETING_FETCH_DROGON=ON \
    && cmake --build build --parallel 2 \
    && ctest --test-dir build --output-on-failure

FROM ubuntu:24.04 AS runtime

ARG DEBIAN_FRONTEND=noninteractive
ARG UBUNTU_MIRROR=""

RUN set -- \
    && if [ -n "$UBUNTU_MIRROR" ]; then \
        test -f /etc/apt/sources.list.d/ubuntu.sources \
        && sed -i -E "s#https?://(archive|security)\.ubuntu\.com/ubuntu/?#${UBUNTU_MIRROR%/}#g" /etc/apt/sources.list.d/ubuntu.sources \
        && set -- -o Acquire::http::Proxy=DIRECT -o Acquire::https::Proxy=DIRECT; \
    fi \
    && apt-get "$@" update \
    && apt-get "$@" install -y --no-install-recommends \
        ca-certificates \
        curl \
        libbrotli1 \
        libargon2-1 \
        libc-ares2 \
        libjsoncpp25 \
        libhiredis1.1.0 \
        libpq5 \
        libssl3t64 \
        libuuid1 \
        zlib1g \
    && test -s /etc/ssl/certs/ca-certificates.crt \
    && case "$UBUNTU_MIRROR" in \
        http://*) mirror_pattern=$(printf '%s' "${UBUNTU_MIRROR%/}" | sed 's/[][\\.^$*#]/\\&/g') \
            && sed -i "s#${mirror_pattern}#https://${UBUNTU_MIRROR#http://}#g" /etc/apt/sources.list.d/ubuntu.sources ;; \
    esac \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /src/build/ticketing_backend /app/ticketing_backend
COPY config /app/config

RUN ldd /app/ticketing_backend | grep -E 'libargon2|libhiredis|not found' \
    && ! ldd /app/ticketing_backend | grep 'not found'

EXPOSE 8080

CMD ["./ticketing_backend", "config/config.docker.json"]

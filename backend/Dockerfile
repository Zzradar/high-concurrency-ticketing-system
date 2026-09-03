FROM ubuntu:24.04 AS build

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        libbrotli-dev \
        libc-ares-dev \
        libjsoncpp-dev \
        libhiredis-dev \
        libpq-dev \
        libssl-dev \
        python3 \
        uuid-dev \
        zlib1g-dev \
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

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libbrotli1 \
        libc-ares2 \
        libjsoncpp25 \
        libhiredis1.1.0 \
        libpq5 \
        libssl3t64 \
        libuuid1 \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /src/build/ticketing_backend /app/ticketing_backend
COPY config /app/config

RUN ldd /app/ticketing_backend | grep -E 'libhiredis|not found' \
    && ! ldd /app/ticketing_backend | grep 'not found'

EXPOSE 8080

CMD ["./ticketing_backend", "config/config.docker.json"]

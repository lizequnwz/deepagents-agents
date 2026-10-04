ARG CODING_BASE_IMAGE
FROM golang:1.27.1-bookworm AS go
FROM rust:1.98.1-bookworm AS rust
FROM eclipse-temurin:21.0.12.1_1-jdk-jammy AS java
FROM ${CODING_BASE_IMAGE}

USER root
LABEL io.general-agent.coding-toolchains="go-1.27.1,rust-1.98.1,java-21.0.12.1"
COPY --from=go /usr/local/go /usr/local/go
COPY --from=rust /usr/local/cargo/bin /usr/local/cargo/bin
COPY --from=rust /usr/local/rustup /usr/local/rustup
COPY --from=java /opt/java/openjdk /opt/java/openjdk
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/local/go/bin/go /usr/local/bin/go \
    && ln -s /usr/local/go/bin/gofmt /usr/local/bin/gofmt \
    && ln -s /usr/local/cargo/bin/rustup /usr/local/bin/rustup \
    && ln -s /usr/local/cargo/bin/cargo /usr/local/bin/cargo \
    && ln -s /usr/local/cargo/bin/rustc /usr/local/bin/rustc \
    && ln -s /usr/local/cargo/bin/rustfmt /usr/local/bin/rustfmt \
    && ln -s /opt/java/openjdk/bin/java /usr/local/bin/java \
    && ln -s /opt/java/openjdk/bin/javac /usr/local/bin/javac
ENV GOROOT=/usr/local/go GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off \
    RUSTUP_HOME=/usr/local/rustup CARGO_NET_OFFLINE=true JAVA_HOME=/opt/java/openjdk
RUN go version && cargo --version && rustc --version && java -version && javac -version
USER 1000:1000

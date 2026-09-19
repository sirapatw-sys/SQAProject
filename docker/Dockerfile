FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Los_Angeles

# Keep Java/Ant source decoding deterministic and UTF-8.
# C.UTF-8 is available in the Ubuntu base image and avoids the US-ASCII
# default that breaks older Defects4J projects containing Unicode source text.
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-11-jdk \
    perl \
    git \
    subversion \
    curl \
    ca-certificates \
    make \
    gcc \
    build-essential \
    unzip \
    cpanminus \
    && rm -rf /var/lib/apt/lists/*

RUN cpanm --notest \
    DBD::CSV \
    DBI \
    JSON \
    JSON::Parse \
    Perl::Critic \
    String::Interpolate \
    URI

ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV PATH="/opt/defects4j/framework/bin:${JAVA_HOME}/bin:${PATH}"

WORKDIR /workspace

CMD ["bash"]

FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Los_Angeles

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

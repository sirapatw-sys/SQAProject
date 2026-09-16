FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Los_Angeles
ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV PATH="/opt/defects4j/framework/bin:${PATH}"

RUN apt-get update -y && \
    apt-get install -y \
      openjdk-11-jdk \
      git \
      build-essential \
      subversion \
      perl \
      curl \
      unzip \
      cpanminus \
      make \
      python3 \
      python3-pip \
      python3-venv \
      ca-certificates \
      tzdata && \
    rm -rf /var/lib/apt/lists/*

# Install Defects4J Perl dependencies
COPY docker/cpanfile /tmp/defects4j-perl/cpanfile

RUN cd /tmp/defects4j-perl && \
    cpanm --notest --installdeps .

WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt

RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

CMD ["bash"]
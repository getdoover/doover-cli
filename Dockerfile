#FROM ubuntu:22.04
#
#ENV DEBIAN_FRONTEND=noninteractive
#
#RUN apt-get update && apt-get install -y wget
#
## In case we depend on any internal apt packages, add the doover repository
#RUN wget -O /etc/apt/keyrings/doover.asc http://apt.u.doover.com/gpg &&  \
#    chmod a+r /etc/apt/keyrings/doover.asc && \
#    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/doover.asc] http://apt.u.doover.com/ stable main" | tee /etc/apt/sources.list.d/doover.list > /dev/null
#
#RUN apt update && apt install -y \
#    build-essential \
#    git-buildpackage \
#    debhelper \
#    equivs \
#    dh-exec \
#    curl

FROM spaneng/doover-apt-cicd-base

RUN apt update && apt install -y \
            build-essential \
            git-buildpackage \
            debhelper \
            equivs \
            dh-exec \
            curl

COPY . .

RUN echo 'y' | mk-build-deps -i debian/control
RUN #apt install pybuild-plugin-pyproject
RUN debuild
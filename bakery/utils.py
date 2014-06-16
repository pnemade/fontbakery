# coding: utf-8
# Copyright 2013 The Font Bakery Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# See AUTHORS.txt for the list of Authors and LICENSE.txt for the License.
from __future__ import print_function
from datetime import datetime

import glob
import io
import itsdangerous
import os
import os.path as op
import subprocess

from flask import current_app
from scripts.genmetadata import sortOldMetadata as sortMetadata


import sys
if sys.version < '3':
    import codecs

    def uniescape(value):
        return codecs.unicode_escape_decode(value)[0]
else:
    def uniescape(value):
        return value


def get_current_time():
    return datetime.utcnow()


def pretty_date(date, default=None):
    """
    Returns string representing "time since" e.g.
    3 days ago, 5 hours ago etc.
    Ref: https://bitbucket.org/danjac/newsmeme/src/a281babb9ca3/newsmeme/
    """

    if default is None:
        default = 'just now'

    diff = datetime.utcnow() - date

    periods = (
        (diff.days / 365, 'year', 'years'),
        (diff.days / 30, 'month', 'months'),
        (diff.days / 7, 'week', 'weeks'),
        (diff.days, 'day', 'days'),
        (diff.seconds / 3600, 'hour', 'hours'),
        (diff.seconds / 60, 'minute', 'minutes'),
        (diff.seconds, 'second', 'seconds'),
    )

    for period, singular, plural in periods:

        if not period:
            continue

        if period == 1:
            return u'%d %s ago' % (period, singular)
        else:
            return u'%d %s ago' % (period, plural)

    return default


def signify(text):
    signer = itsdangerous.Signer(current_app.secret_key)
    return signer.sign(text)


class RedisFd(object):
    """ Redis File Descriptor class, publish writen data to redis channel
        in parallel to file """
    def __init__(self, name, mode='a'):
        self.filed = open(name, mode)
        self.filed.write("Start: Start of log\n")  # end of log

    def write(self, data, prefix=''):
        self.filed.write("%s%s" % (prefix, data))
        self.filed.flush()

    def close(self):
        self.filed.write("End: End of log\n")  # end of log
        self.filed.close()


def project_fontaine(project, build):
    from fontaine.font import FontFactory

    param = {'login': project.login, 'id': project.id,
             'revision': build.revision, 'build': build.id}

    _out = op.join(current_app.config['DATA_ROOT'],
                   '%(login)s/%(id)s.out/%(build)s.%(revision)s/' % param)

    # Its very likely that _out exists, but just in case:
    if op.exists(_out):
        os.chdir(_out)
    else:
        # This is very unlikely, but should it happen, just return
        return

    # Run pyFontaine on all the TTF fonts
    fonts = {}
    for filename in glob.glob("*.ttf"):
        fontaine = FontFactory.openfont(filename)
        fonts[filename] = fontaine

    # Make a plain dictionary, unlike the fancy data structures
    # used by pyFontaine :)
    family = {}
    for fontfilename, fontaine in fonts.iteritems():
        # Use the font file name as a key to a dictionary of char sets
        family[fontfilename] = {}
        for orthography in fontaine.get_orthographies():
            charset, coverage, percent_complete, missing_chars = orthography
            # Use each charset name as a key to dictionary of font's
            # coverage details
            charset = charset.common_name
            family[fontfilename][charset] = {}
            # unsupport, fragmentary, partial, full
            family[fontfilename][charset]['coverage'] = coverage
            family[fontfilename][charset]['percentcomplete'] = percent_complete
            # list of ord numbers
            family[fontfilename][charset]['missingchars'] = missing_chars
            # Use the char set name as a key to a list of the family's
            # average coverage
            if not charset in family:
                family[charset] = []
            # Append the char set percentage of each font file to the list
            family[charset].append(percent_complete)  # [10, 32, 40, 40] etc
            # And finally, if the list now has all the font files, make it
            # the mean average percentage
            if len(family[charset]) == len(fonts.items()):
                family[charset] = sum(family[charset]) / len(fonts.items())
    # Make a plain dictionary with just the bits we want on the dashboard
    totals = {}
    totals['gwf'] = family.get('GWF latin', None)
    totals['al3'] = family.get('Adobe Latin 3', None)
    # Store it in the $(id).state.yaml file
    project.config['local']['charsets'] = totals
    project.save_state()

    # fonts.itervalues() emits fontaine.font.Font instances that are used
    # for the rfiles.html template
    return fonts.itervalues()


def striplines(jsontext):
    lines = jsontext.split("\n")
    newlines = []
    for line in lines:
        newlines.append("%s\n" % (line.rstrip()))
    return "".join(newlines)


def save_metadata(metadata, path):
    # flask json serializer doesn't support OrderedDict
    import json
    data = json.loads(uniescape(metadata))
    ready_data = sortMetadata(data)
    dump = json.dumps(ready_data, indent=2, ensure_ascii=True)
    strip_dump = striplines(dump)
    with io.open(path, 'w', encoding='utf-8') as filep:
        filep.write(uniescape(strip_dump))


from math import log
unit_list = zip(['', 'k', 'M', 'B'], [0, 0, 1, 2])


def sizeof_fmt(num):
    """Human friendly file size"""
    if num > 1:
        exponent = min(int(log(num, 1000)), len(unit_list) - 1)
        quotient = float(num) / 1000 ** exponent
        unit, num_decimals = unit_list[exponent]
        format_string = '{:.%sf} {}' % (num_decimals)
        return format_string.format(quotient, unit)
    if num == 0:
        return '0'
    if num == 1:
        return '1'


def short(value):
    if not value:
        return 0
    try:
        value = int(value)
        if not value:
            return 0
    except ValueError:
        return 0

    return '~{}'.format(sizeof_fmt(value))


def run(command, cwd, log):
    """ Wrapper for subprocess.Popen with custom logging support.

        :param command: shell command to run, required
        :param cwd: - current working dir, required
        :param log: - logging object with .write() method, required

    """
    # print the command on the worker console
    print("[%s]:%s" % (cwd, command))
    # log the command
    log.write('\n$ %s\n' % command)
    # Start the command
    env = os.environ.copy()
    env.update({'PYTHONPATH': os.pathsep.join(sys.path)})
    process = subprocess.Popen(command, shell=True, cwd=cwd,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               close_fds=True, env=env)
    while True:
        # Read output and errors
        stdout = process.stdout.readline()
        stderr = process.stderr.readline()
        # Log output
        log.write(stdout)
        # Log error
        if stderr:
            # print the error on the worker console
            print(stderr, end='')
            # log error
            log.write(stderr, prefix='Error: ')
        # If no output and process no longer running, stop
        if not stdout and not stderr and process.poll() is not None:
            break
    # if the command did not exit cleanly (with returncode 0)
    if process.returncode:
        msg = 'Fatal: Exited with return code %s \n' % process.returncode
        # Log the exit status
        log.write(msg)
        # Raise an error on the worker
        raise StandardError(msg)


def prun(command, cwd, log=None):
    """
    Wrapper for subprocess.Popen that capture output and return as result

        :param command: shell command to run
        :param cwd: current working dir
        :param log: loggin object with .write() method

    """
    # print the command on the worker console
    print("[%s]:%s" % (cwd, command))
    env = os.environ.copy()
    env.update({'PYTHONPATH': os.pathsep.join(sys.path)})
    process = subprocess.Popen(command, shell=True, cwd=cwd,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,
                               close_fds=True, env=env)
    if log:
        log.write('$ %s\n' % command)

    stdout = ''
    for line in iter(process.stdout.readline, ''):
        if log:
            log.write(line)
        stdout += line
        process.stdout.flush()
    return stdout

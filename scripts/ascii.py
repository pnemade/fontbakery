#!/usr/bin/python
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

import os

from cli.ttfont import Font


def fix_name_table(fontfile):
    font = Font(fontfile)
    for name_record in font['name'].names:
        name_record.string = Font.bin2unistring(name_record.string)
    font.save(fontfile + '.fix')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('filename', help="Font file in TTF format")

    args = parser.parse_args()
    assert os.path.exists(args.filename)
    fix_name_table(args.filename)

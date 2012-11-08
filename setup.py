#!/usr/bin/env python

from distutils.core import setup

with open('LICENSE.md', 'r') as f:
    licence = f.read().split('\n')

setup(name='jira2fogbugz',
      version='0.1',
      description='Jira to Fogbugz case importer',
      author='Igor Serko',
      author_email='igor.serko@gmail.com',
      url='https://github.com/iserko/jira2fogbugz',
      package_dir = {'': 'src'},
      py_modules = ['jira2fogbugz'],
      licence=licence,
     )

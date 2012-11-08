#!/usr/bin/env python
from setuptools import setup, find_packages

with open('LICENSE.md', 'r') as f:
    license = f.read().split('\n')

setup(name='jira2fogbugz',
      version='0.1',
      description='Jira to Fogbugz case importer',
      author='Igor Serko',
      author_email='igor.serko@gmail.com',
      url='https://github.com/iserko/jira2fogbugz',
      package_dir = {'': 'src'},
      packages = find_packages('src'),
      install_requires = ['setuptools',
                          'jira-python',
                          'fogbugz'],
      entry_points = {
          'console_scripts': [
              'jira2fogbugz = jira2fogbugz:run',
          ],
      },
      license=license,
     )

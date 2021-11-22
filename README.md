# README #

Specific ISP network L2 service explorer auditor. This script was intended to collect ISP network devices services and auditing them to find not or wrong configured services.

Script retreive inventory network devices configuration and parse it including Huawei and Juniper vendors. After that it gather configured services according to engineering rules.

After all it export a JSON document database with all the imported nodes and set of services gathered.


## Requirements ##

It's needed several requirements like, most of them won't be included on repo for NDA reasons:

    1. ISP input node list form it's inventory
    2. URLs from where to gather configuration files (in plain text from each vendor backup config file format)



## LICENSE
### GNU GPL v3
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

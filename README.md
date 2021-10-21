# Fishbowl API

A Python wrapper for the Fishbowl Inventory API.

Currently supports add inventory request, cycle inventory count::

```python
add_inventory(part_number, quantity, UOM_ID, cost, location_tag_num)
cycle_inventory(part_number, new_qty, location_id)
```

Example usage

```
from fishbowl.api import Fishbowl

fishbowl_api = Fishbowl()
fishbowl_api.connect(username='admin', password='admin', host='10.0.2.2')
fishbowl_api.add_inventory('B500', 5, 1, 50.00, 386)
fishbowl_api.close()
```

## Fresh setup for development

1. checkout Code
2. create virtualenv `python -m venv .venv --prompt=fishbowl-api`
3. `pip install -r requirements.pip`
4. `pip install -e .`
5. Setup a `fishbowl/fishbowl.ini` file
6. To run example.py `python fishbowl/__init__.py`

### Example fishbowl.ini

```
[connect]
host = 192.168.1.10
port = 28192
timeout = 6000
username = someuser
password = somepassword
```

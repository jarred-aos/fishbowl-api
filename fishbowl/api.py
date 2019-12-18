from __future__ import unicode_literals
import base64
import csv
import socket
import struct
import hashlib
import functools
import logging
import sys
import time
from functools import partial
from lxml import etree

from io import StringIO

from . import xmlrequests, statuscodes, objects

logger = logging.getLogger(__name__)

PRICING_RULES_SQL = (
    "SELECT p.id, p.isactive, product.num, "
    "p.patypeid, p.papercent, p.pabaseamounttypeid, p.paamount, "
    "p.customerincltypeid, p.customerinclid "
    "from pricingrule p INNER JOIN product on p.productinclid = product.id "
    "where p.productincltypeid = 2 and "
    "p.customerincltypeid in (1, 2)"
)


CUSTOMER_GROUP_PRICING_RULES_SQL = (
    "SELECT p.id, p.isactive, product.num, p.patypeid, p.papercent, "
    "p.pabaseamounttypeid, p.paamount, p.customerincltypeid, "
    "p.customerinclid, c.id as customerid, ag.name as accountgroupname, "
    "c.name as customername "
    "FROM pricingrule p "
    "INNER JOIN product ON p.productinclid = product.id "
    "INNER JOIN accountgroup ag ON p.customerinclid = ag.id "
    "INNER JOIN accountgrouprelation agr ON agr.groupid = ag.id "
    "INNER JOIN customer c ON agr.accountid = c.accountid "
    "WHERE p.productincltypeid = 2 AND p.customerincltypeid = 3"
)

PRODUCTS_SQL = (
    "SELECT P.*, PART.STDCOST AS StandardCost, PART.TYPEID as TypeID "
    "{ci_fields} FROM PRODUCT P "
    "INNER JOIN PART ON P.PARTID = PART.ID {custom_joins}"
)


PARTS_SQL = (
    "SELECT id, num, stdCost as StandardCost, description, typeID, "
    "dateLastModified, dateCreated, len, serializedFlag "
    "FROM Part"
)


def UnicodeDictReader(utf8_data, **kwargs):
    csv_reader = csv.DictReader(utf8_data, **kwargs)
    for row in csv_reader:
        yield {key: value for key, value in row.items()}


class FishbowlError(Exception):
    pass


class FishbowlTimeoutError(FishbowlError):
    pass


class FishbowlConnectionError(FishbowlError):
    pass


def require_connected(func):
    """
    A decorator to wrap :cls:`Fishbowl` methods that can only be called after a
    connection to the API server has been made.
    """

    @functools.wraps(func)
    def dec(self, *args, **kwargs):
        if not self.connected:
            logger.error("API method called but Fishbowl is not connected")
            raise OSError("Not connected")
        return func(self, *args, **kwargs)

    return dec


class Fishbowl:
    """
    Fishbowl API connection.

    For standard higher level usage, use the :cls:`FishbowlAPI` that creates
    instances of this class as required.

    Example usage::

        fishbowl = Fishbowl()
        fishbowl.connect(
            username='admin', password='pw', host='10.0.0.1', port=28192)
    """

    host = "localhost"
    port = 28192
    encoding = "latin-1"
    login_timeout = 3

    def __init__(self, task_name=None):
        self._connected = False
        self.task_name = task_name

    @property
    def connected(self):
        return self._connected

    def make_stream(self, timeout=5, retry=3):
        """
        Create a connection to communicate with the API.
        """
        logger.info("Connecting to %s:%s", self.host, self.port)
        while True:
            stream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            stream.settimeout(self.login_timeout)
            try:
                stream.connect((self.host, self.port))
                break
            except socket.error as e:
                msg = getattr(e, "strerror", None) or e.message
                if not retry:
                    logger.exception("Fishbowl API connection failure, giving up")
                    raise FishbowlConnectionError(msg)
                logger.warning("Fishbowl API connection failure, retrying: %s", msg)
                time.sleep(5)
                retry -= 1
        stream.settimeout(timeout)
        return stream

    def connect(self, username, password, host, port, timeout=5):
        """
        Open socket stream, set timeout, and log in.
        """
        password = base64.b64encode(hashlib.md5(password.encode(self.encoding)).digest()).decode(
            "ascii"
        )

        if self.connected:
            self.close()

        self.host = host
        self.port = int(port)
        self.stream = self.make_stream(timeout=float(timeout))
        self._connected = True

        try:
            self.key = None
            login_xml = xmlrequests.Login(username, password, task_name=self.task_name).request
            response = self.send_message(login_xml)
            # parse xml, grab api key, check status
            for element in response.iter():
                if element.tag == "Key":
                    self.key = element.text
                if element.tag in ("loginRs", "LoginRs", "FbiMsgsRs"):
                    check_status(element, allow_none=True)

            if not self.key:
                msg = "No login key in response"
                logger.error(msg)
                raise FishbowlError(msg)
        except Exception:
            logger.exception(
                "Unexpected exception while connecting to Fishbowl, closing connection"
            )
            self.close(skip_errors=True)
            raise
        self.username = username

    def close(self, skip_errors=False):
        """
        Close connection to Fishbowl API.
        """
        try:
            has_key = getattr(self, "key", None)
            if has_key:
                # Unset key first to avoid a loop if the logout request fails.
                self.key = None
                logout_xml = xmlrequests.Login(
                    self.username, "", logout=self.key, task_name=self.task_name
                ).request
                logout_response = self.send_message(logout_xml)
            if not self.connected:
                raise OSError("Not connected")
            self._connected = False
            self.stream.close()
            if has_key:
                check_status(logout_response.find("FbiMsgsRs"), expected="1010")
        except Exception:
            if not skip_errors:
                logger.exception(
                    "Unexpected error while trying to close the Fishbowl " "connection"
                )
                raise

    def pack_message(self, msg):
        """
        Calculate msg length and prepend to msg.
        """
        msg_length = len(msg)
        # '>L' = 4 byte unsigned long, big endian format
        packed_length = struct.pack(">L", msg_length)
        return packed_length + msg

    @require_connected
    def send_request(
        self, request, value=None, response_node_name=None, single=True, silence_errors=False,
    ):
        """
        Send a simple request to the API that follows the standard method.

        :param request: A :cls:`fishbowl.xmlrequests.Request` instance, or text
            containing the name of the base XML node to create
        :param value: A string containing the text of the base node, or a
            dictionary mapping to children nodes and their values (only used if
            request is just the text node name)
        :param response_node_name: Find and return this base response XML node
        :param single: Expect and return the single child of
            ``response_node_name`` (default ``True``)
        :param silence_errors: Return an empty XML node rather than raising an
            error if the response returns an unexpected status code (default
            ``False``)
        """
        if isinstance(request, str):
            request = xmlrequests.SimpleRequest(request, value, key=self.key)
        root = self.send_message(request)
        if response_node_name:
            try:
                resp = root.find("FbiMsgsRs")
                check_status(resp, allow_none=True)
                root = resp.find(response_node_name)
                check_status(root, allow_none=True)
            except FishbowlError:
                if silence_errors:
                    return etree.Element("empty")
                logger.error("Unexpected response status")
                raise
            if single:
                if len(root):
                    root = root[0]
                else:
                    root = etree.Element("empty")
        return root

    @require_connected
    def send_query(self, query):
        """
        Send a SQL query to be executed on the server, returning a
        ``DictReader`` containing the rows returned as a list of dictionaries.
        """
        response = self.send_request(
            "ExecuteQueryRq", {"Query": query}, response_node_name="ExecuteQueryRs"
        )
        csvfile = StringIO()
        for row in response.iter("Row"):
            # csv.DictReader API changed
            text = f"{row.text}\n"
            csvfile.write(text)
        csvfile.seek(0)
        return UnicodeDictReader(csvfile)

    @require_connected
    def send_message(self, msg):
        """
        Send a message to the API and return the root element of the XML that
        comes back as a response.

        For higher level usage, see :meth:`send_request`.
        """
        if isinstance(msg, xmlrequests.Request):
            msg = msg.request

        tag = "unknown"
        try:
            xml = etree.fromstring(msg)
            request_tag = xml.find("FbiMsgsRq")
            if request_tag is not None and len(request_tag):
                tag = request_tag[0].tag
        except etree.XMLSyntaxError:
            pass
        logger.info("Sending message ({})".format(tag))
        logger.debug("Sending message:\n" + msg.decode(self.encoding))
        self.stream.send(self.pack_message(msg))

        # Get response
        byte_count = 0
        response = bytearray()
        received_length = False
        try:
            packed_length = b""
            while len(packed_length) < 4:
                packed_length += self.stream.recv(4 - len(packed_length))
            length = struct.unpack(">L", packed_length)[0]
            received_length = True
            while byte_count < length:
                byte = ord(self.stream.recv(1))
                byte_count += 1
                response.append(byte)
        except socket.timeout:
            self.close(skip_errors=True)
            if received_length:
                msg = "Connection timeout (after length received)"
            else:
                msg = "Connection timeout"
            logger.exception(msg)
            raise FishbowlTimeoutError(msg)
        response = response.decode(self.encoding)
        logger.debug("Response received:\n" + response)
        return etree.fromstring(response)

    @require_connected
    def add_inventory(self, partnum, qty, uomid, cost, loctagnum):
        """
        Add inventory.
        """
        request = xmlrequests.AddInventory(partnum, qty, uomid, cost, loctagnum, key=self.key)
        response = self.send_message(request)
        for element in response.iter("AddInventoryRs"):
            check_status(element, allow_none=True)
            logger.info(
                ",".join(
                    ["{}".format(val) for val in ["add_inv", partnum, qty, uomid, cost, loctagnum]]
                )
            )

    @require_connected
    def get_part_info(self, partnum):
        """
        Returns all information relating to a part
        """
        request = xmlrequests.InventoryQuantity(partnum, key=self.key)
        return self.send_message(request)

    @require_connected
    def get_total_inventory(self, partnum, locationid):
        """
        Returns total inventory count at specified location
        """
        request = xmlrequests.GetTotalInventory(partnum, locationgroup, key=self.key)
        return self.send_message(request)

    @require_connected
    def get_locations(self, partnum, locationgroup=None):
        """
        Returns locations of the specified part
        """
        response = self.get_part_info(partnum)
        if locationgroup:
            locations = []
            for item in response[1][0]:
                if next(item[1].iterfind("./LocationGroupName")).text == locationgroup:
                    locations.append(
                        {
                            "location": item[1][0].text,
                            "location_name": item[1][2].text,
                            "description": item[1][3].text,
                            "available_quantity": int(item[3].text),
                            "total_quantity": int(item[2].text),
                        }
                    )
        else:
            locations = [
                {
                    "location": item[1][0].text,
                    "location_name": item[1][2].text,
                    "description": item[1][3].text,
                    "available_quantity": int(item[3].text),
                    "total_quantity": int(item[2].text),
                }
                for item in response[1][0]
            ]
        return locations

    @require_connected
    def cycle_inventory(self, partnum, qty, locationid):
        """
        Cycle inventory of part in Fishbowl.
        """
        request = xmlrequests.CycleCount(partnum, qty, locationid, key=self.key)
        response = self.send_message(request)
        for element in response.iter("CycleCountRs"):
            check_status(element, allow_none=True)
            logger.info(
                ",".join(["{}".format(val) for val in ["cycle_inv", partnum, qty, locationid]])
            )

    @require_connected
    def get_po_list(self, locationgroup):
        """
        Get list of POs.
        """
        request = xmlrequests.GetPOList(locationgroup, key=self.key)
        return self.send_message(request)

    @require_connected
    def get_taxrates(self):
        """
        Get tax rates.

        :returns: A list of :cls:`fishbowl.objects.TaxRate` objects
        """
        response = self.send_request(
            "TaxRateGetRq", response_node_name="TaxRateGetRs", single=False
        )
        return [objects.TaxRate(node) for node in response.iter("TaxRate")]

    @require_connected
    def get_location_groups(self, only_active=True):
        """
        Get location groups.

        :returns: A list of :cls:`fishbowl.objects.LocationGroup` objects
        """
        location_groups = []
        for row in self.send_query("SELECT * FROM LOCATIONGROUP"):
            obj = objects.LocationGroup(row)
            if not only_active or obj["ActiveFlag"]:
                location_groups.append(obj)
        return location_groups

    @require_connected
    def get_customers(self, lazy=True, silence_lazy_errors=True):
        """
        Get customers.

        :lazy: Lazily load all customer data when it's requested rather than
               proload all data in one lump. This will also load in the
               addresses for each customer which doesn't happen in non-lazy
               mode (defaults to True).
        :returns: A list of :cls:`fishbowl.objects.Customer` objects
        """
        if not lazy:
            response = self.send_request(
                "CustomerListRq", response_node_name="CustomerListRs", single=False
            )
            return [objects.Customer(node) for node in response.iter("Customer")]
        customers = []
        response = self.send_request(
            "CustomerNameListRq", response_node_name="CustomerNameListRs", single=False
        )
        for tag in response.iter("Name"):
            get_customer = partial(
                self.send_request,
                "CustomerGetRq",
                {"Name": tag.text},
                response_node_name="CustomerGetRs",
                silence_errors=silence_lazy_errors,
            )
            customer = objects.Customer(lazy_data=get_customer, name=tag.text)
            customers.append(customer)
        return customers

    @require_connected
    def get_uom_map(self):
        response = self.send_request("UOMRq", response_node_name="UOMRs", single=False)
        return dict(
            (uom["UOMID"], uom) for uom in [objects.UOM(node) for node in response.iter("UOM")]
        )

    @require_connected
    def get_parts(self, populate_uoms=True):
        """
        Get a light list of parts.

        :param populate_uoms: Whether to populate the UOM for each part
            (default ``True``)
        :returns: A list of cls:`fishbowl.objects.Part`
        """
        response = self.send_request(
            "LightPartListRq", response_node_name="LightPartListRs", single=False
        )
        parts = [objects.Part(node) for node in response.iter("LightPart")]
        if populate_uoms:
            uom_map = self.get_uom_map()
            for part in parts:
                uomid = part.get("UOMID")
                if not uomid:
                    continue
                uom = uom_map.get(uomid)
                if uom:
                    part.mapped["UOM"] = uom
        return parts

    @require_connected
    def get_parts_all(self):
        parts = []

        for row in self.send_query(PARTS_SQL):
            part = objects.Part(row)
            if not part:
                continue

            parts.append(part)

        return parts

    @require_connected
    def get_products(self, lazy=True):
        """
        Get a list of products, optionally lazy.

        The tricky thing is that there's no direct API for a product list, so
        we have to get a list of parts and then find the matching products.
        Understandably then, the non-lazy option is intensive, while the lazy
        option results in some products potentially being empty.

        :param lazy: Whether the products should be lazily loaded (default
            ``True``)
        :returns: A list of cls:`fishbowl.objects.Product`
        """
        products = []
        added = []
        for part in self.get_parts(populate_uoms=False):
            part_number = part.get("Num")
            # Skip parts without a number, and duplicates.
            if not part_number or part_number in added:
                continue

            get_product = partial(
                self.send_request,
                "ProductGetRq",
                {"Number": part_number},
                response_node_name="ProductGetRs",
            )

            product_kwargs = {
                "name": part_number,
            }
            if lazy:
                product_kwargs["lazy_data"] = get_product
            else:
                product_node = get_product()
                if not len(product_node):
                    continue
                product_kwargs["data"] = product_node
            product = objects.Product(**product_kwargs)
            product.part = part
            products.append(product)
            added.append(part_number)
        return products

    @require_connected
    def get_products_fast(self, populate_uoms=True, custom_bools=None):
        """
        Quickly get all products.

        Here is an example of how to use ``Part`` custom fields::

            >>> products = connection.get_products_fast(
                 custom_bools={'ApiFieldName': 'Fishbowl custom field name'})
            >>> products[0].part['ApiFieldName']
            False
        """
        products = []
        if populate_uoms:
            uom_map = self.get_uom_map()

        # Handle custom fields.
        custom_fields = {}
        ci_fields, custom_joins = [], []
        if custom_bools:
            for field, name in custom_bools.items():
                ci_fields.append("CI.INFO AS {}".format(field))
                custom_joins.append(
                    """
LEFT JOIN CUSTOMINTEGER CI ON CI.recordid = PART.ID AND CI.customfieldid = (
 select customfield.id from customfield
 inner join tablereference t on customfield.tableid=t.tableid
 where t.tablerefname='Part' and name='{}')""".format(
                        name
                    )
                )
                custom_fields[field] = objects.fishbowl_boolean
        sql = PRODUCTS_SQL.format(
            ci_fields="".join(", " + ci_field for ci_field in ci_fields),
            custom_joins=" ".join(custom_joins),
        )

        for row in self.send_query(sql):
            product = objects.Product(row, name=row.get("NUM"))
            if not product:
                continue
            if populate_uoms:
                uomid = row.get("UOMID")
                if uomid:
                    uom = uom_map.get(int(uomid))
                    if uom:
                        product.mapped["UOM"] = uom
            product.part = objects.Part(row, custom_fields=custom_fields)
            products.append(product)
        return products

    @require_connected
    def get_pricing_rules(self):
        """
        Get a list of pricing rules for products.

        :returns: A dictionary of pricing rules, where each key is the customer
            id and value a list of rules. A key of ``None`` is used for pricing
            rules relevant to all customers.
        """
        pricing_rules = {None: []}

        def process_rules(data, rules):
            for row in data:
                customer_type = row.pop("CUSTOMERINCLTYPEID")
                customer_id = row.pop("CUSTOMERINCLID")
                if customer_type == "1":
                    customer_id = None
                elif customer_type == "3":
                    customer_id = int(row.pop("CUSTOMERID"))
                else:
                    customer_id = int(customer_id)
                customer_pricing = rules.setdefault(customer_id, [])
                customer_pricing.append(row)

        process_rules(self.send_query(PRICING_RULES_SQL), pricing_rules)
        process_rules(self.send_query(CUSTOMER_GROUP_PRICING_RULES_SQL), pricing_rules)

        return pricing_rules

    @require_connected
    def get_customers_fast(self, populate_addresses=True, populate_pricing_rules=False):
        customers = []
        # contact_map = dict(
        #     (contact['ACCOUNTID'], contact['NAME']) for contact in
        #     self.send_query('SELECT * FROM CONTACT'))
        if populate_addresses:
            country_map = {}
            for country in self.send_query("SELECT * FROM COUNTRYCONST"):
                country["CODE"] = country["ABBREVIATION"]
                country_map[country["ID"]] = objects.Country(country)
            state_map = dict(
                (state["ID"], objects.State(state))
                for state in self.send_query("SELECT * FROM STATECONST")
            )
            address_map = {}
            for addr in self.send_query("SELECT * FROM ADDRESS"):
                addresses = address_map.setdefault(addr["ACCOUNTID"], [])
                address = objects.Address(addr)
                if address:
                    country = country_map.get(addr["COUNTRYID"])
                    if country:
                        address.mapped["Country"] = country
                    state = state_map.get(addr["STATEID"])
                    if state:
                        address.mapped["State"] = state
                    addresses.append(address)
        if populate_pricing_rules:
            pricing_rules = self.get_pricing_rules()
        for row in self.send_query("SELECT * FROM CUSTOMER"):
            customer = objects.Customer(row)
            if not customer:
                continue
            # contact = contact_map.get(row['ACCOUNTID'])
            # if contact:
            #     customer.mapped['Attn'] = contact['NAME']
            if populate_addresses:
                customer.mapped["Addresses"] = address_map.get(customer["AccountID"], [])
            if populate_pricing_rules:
                rules = []
                rules.extend(pricing_rules[None])
                rules.extend(pricing_rules.get(customer["AccountID"], []))
                customer.mapped["PricingRules"] = rules
            customers.append(customer)
        return customers

    @require_connected
    def get_so(self, number):
        response = self.send_request("LoadSORq", {"Number": number}, response_node_name="LoadSORs")
        if response is None or response.tag != "SalesOrder":
            return None
        return objects.SalesOrder(response)

    @require_connected
    def save_so(self, so):
        request = xmlrequests.SaveSO(so, key=self.key)
        response = self.send_message(request)
        check_status(response.find("FbiMsgsRs"))
        return objects.SalesOrder(response.find("SalesOrder"))


class FishbowlAPI:
    """
    Create (preferably short lived) Fishbowl connections.

    Example usage::

        from fishbowl.api import FishbowlAPI
        fishbowl_api = FishbowlAPI(
            username='admin', password='pw', host='10.0.0.1', port=28192)

        def my_func():
            with fishbowl_api as connection:
                products = connection.get_products()

            # Keep the connection open as short as possible by handling logic
            # outside of the loop.
            process_products(products)
    """

    def __init__(self, task_name=None, **connection_args):
        self.task_name = task_name
        self.connection_args = connection_args

    def __enter__(self):
        self.fb = Fishbowl(task_name=self.task_name)
        self.fb.connect(**self.connection_args)
        return self.fb

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Close the connection, but only show any errors while attempting this if
        the context didn't raise an exception.
        """
        try:
            self.fb.close(skip_errors=bool(traceback))
        except FishbowlTimeoutError:
            pass


def check_status(element, expected=statuscodes.SUCCESS, allow_none=False):
    """
    Check the status code from an XML node, raising an exception if it wasn't
    the expected code.
    """
    code = element.get("statusCode")
    message = element.get("statusMessage")
    if message is None:
        message = statuscodes.get_status(code)
    if code != expected and (code is not None or not allow_none):
        raise FishbowlError(message)
    return message

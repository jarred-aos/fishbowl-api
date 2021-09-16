SALES_ORDER_NUMBERS = """
SELECT s.id, s.num FROM so s ORDER BY id DESC
"""

SALES_ORDER_LIST = """
SELECT 
    s.id, s.billToAddress, s.billToCity, s.billToCountryId, s.billToName,
    s.billToStateId, s.billToZip, s.carrierId, s.cost, s.currencyId,
    s.currencyRate, s.customerContact, s.customerId, s.customerPO,
    s.dateCompleted, s.dateCreated AS `CreatedDate`, s.dateFirstShip AS `FirstShipDate`,
    s.dateIssued AS `IssuedDate`, s.dateLastModified, s.dateRevision, s.fobPointId,
    s.locationGroupId, s.note, s.num AS `Number`, s.paymentTermsId,
    s.qbClassId, s.registerID, s.salesman, s.salesmanId, s.salesmanInitials,
    s.shipTermsId, s.shipToAddress, s.shipToCity, s.shipToCountryId, s.shipToName,
    s.shipToStateId, s.shipToZip, s.statusId, s.taxRate, s.taxRateId, s.taxRateName,
    s.totalIncludesTax, s.totalPrice, s.totalTax, s.typeId, s.url, s.vendorPO,
    s.priorityId, c.name AS `Carrier`, ss.name AS status, f.name AS fob, 
    st.name AS ShippingTerms, qb.name AS QuickBooksClassName,
    cu.name AS CustomerName, pt.name AS PaymentTerms,
    lg.name AS LocationGroup, cur.code AS CurrencyName
FROM
    so s
LEFT JOIN Carrier c ON s.carrierId = c.id
LEFT JOIN sostatus ss ON s.statusId = ss.id
LEFT JOIN fobpoint f ON s.fobpointid = f.id
LEFT JOIN shipterms st ON s.shiptermsid = st.id
LEFT JOIN qbclass qb ON s.qbclassid = qb.id
LEFT JOIN customer cu ON s.customerid = cu.id
LEFT JOIN paymentterms pt ON s.paymenttermsid = pt.id
LEFT JOIN locationgroup lg ON s.locationgroupid = lg.id
LEFT JOIN currency cur ON s.currencyid = cur.id
"""

SALES_ORDER_ITEMS = """
SELECT
    si.ID, si.adjustamount AS AdjustmentAmount, si.AdjustPercentage, si.CustomerPartNum,
    si.DateLastFulfillment, si.DateLastModified, si.DateScheduledFulfillment,
    si.Description, si.ExchangeSOLineItem, si.ItemAdjustID,
    si.productNum AS ProductNumber, si.qtytofulfill AS Quantity, si.QtyFulfilled,
    si.QtyPicked, si.revLevel AS RevisionLevel, si.ShowItemFlag, si.SOID,
    si.soLineItem AS LineNumber, si.TaxableFlag, si.TotalPrice, si.TotalCost,
    si.typeid AS ItemType, p.price AS ProductPrice, qb.name AS QuickBooksClassName,
    sis.name AS Status, u.code AS UOMCode
FROM soitem si
LEFT JOIN product p ON si.productId = p.id
LEFT JOIN qbclass qb ON si.qbclassid = qb.id
LEFT JOIN soitemstatus sis ON si.statusId = sis.id
LEFT JOIN uom u ON si.uomid = u.id
WHERE si.soid = {sales_order_id}
ORDER BY LineNumber ASC
"""

PRICING_RULES_SQL = (
    "SELECT p.id, p.isactive, product.num, "
    "p.patypeid, p.papercent, p.pabaseamounttypeid, p.paamount, "
    "p.customerincltypeid, p.customerinclid, p.datelastmodified "
    "from pricingrule p INNER JOIN product on p.productinclid = product.id "
    "where p.productincltypeid = 2 and "
    "p.customerincltypeid in (1, 2)"
)


CUSTOMER_GROUP_PRICING_RULES_SQL = (
    "SELECT p.id, p.isactive, product.num, p.patypeid, p.papercent, "
    "p.pabaseamounttypeid, p.paamount, p.customerincltypeid, p.datelastmodified, "
    "p.customerinclid, c.id as customerid, ag.name as accountgroupname, "
    "c.name as customername "
    "FROM pricingrule p "
    "INNER JOIN product ON p.productinclid = product.id "
    "INNER JOIN accountgroup ag ON p.customerinclid = ag.id "
    "INNER JOIN accountgrouprelation agr ON agr.groupid = ag.id "
    "INNER JOIN customer c ON agr.accountid = c.accountid "
    "WHERE p.productincltypeid = 2 AND p.customerincltypeid = 3"
)

# https://www.fishbowlinventory.com/files/databasedictionary/2017/tables/product.html
PRODUCTS_SQL = """
SELECT
    P.*,
    PART.STDCOST AS StandardCost,
    PART.TYPEID as TypeID
    {ci_fields}
FROM PRODUCT P
INNER JOIN PART ON P.PARTID = PART.ID
{custom_joins}
"""

# https://www.fishbowlinventory.com/files/databasedictionary/2017/tables/part.html
PARTS_SQL = "SELECT * FROM Part"


SERIAL_NUMBER_SQL = (
    "SELECT sn.id, sn.serialId, sn.serialNum, p.num as PartNum, "
    "t.dateCreated as DateCreated, t.dateLastModified as DateLastModified "
    "FROM serialnum sn "
    "LEFT JOIN serial s ON s.id = sn.serialId "
    "LEFT JOIN tag t on t.id = s.tagId "
    "LEFT JOIN part p on t.partId = p.id"
)


USERS_SQL = """
SELECT
    id as ID,
    email as Email,
    firstName as FirstName,
    lastName as LastName,
    phone as Phone,
    username as Username
FROM sysuser
"""

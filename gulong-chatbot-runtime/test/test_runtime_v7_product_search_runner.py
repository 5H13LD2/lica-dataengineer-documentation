import runtime_v7.product_search as product_search_module
from runtime_v7.product_search import (
    ProductSearchRequest,
    ProductSearchRunner,
    brand_bucket_legend_text,
    build_brand_buckets,
    installment_summary,
    model_match_score,
    model_match_threshold,
    normalize_metric_section_width_with_corrections,
    normalize_product,
    normalize_rim_size,
    normalize_section_width,
    prefer_image_backed_presentation_products,
    render_brand_bucket_cards,
    render_product_cards,
    rim_matches,
)


class FakeHTTPClient:
    def __init__(self):
        self.post_calls = []
        self.get_calls = []

    def post_json(self, path, *, params=None, json_data=None):
        self.post_calls.append({"path": path, "params": dict(params or {})})
        params = params or {}
        brand_filter = str(params.get("b") or "")
        rim = str(params.get("rim_size") or "")
        section = str(params.get("section_width") or "")
        aspect = str(params.get("aspect_ratio") or "")
        products = []
        if rim == "R15" and brand_filter == "YOKOHAMA" and section == "185" and aspect == "60":
            products = [_raw_product(1, "yoko-bluearth", "YOKOHAMA", "YOKOHAMA 185/60/R15 BLUEARTH ES32 84H", "185", "60", "R15", 4815)]
        elif rim == "R15" and brand_filter == "NEWBRAND":
            products = [_raw_product(99, "newbrand-touring", "NEWBRAND", "NEWBRAND 185/60/R15 TOURING 84H", "185", "60", "R15", 3900)]
        elif rim == "R15" and section == "185" and aspect == "60":
            products = [
                _raw_product(1, "yoko-bluearth", "YOKOHAMA", "YOKOHAMA 185/60/R15 BLUEARTH ES32 84H", "185", "60", "R15", 4815),
                _raw_product(3, "atlas-force", "ATLAS", "ATLAS 185/60/R15 FORCE HP 84H", "185", "60", "R15", 3040, origin_country="China", warranty="1 year", tire_type="Budget"),
                _raw_product(4, "michelin-xm2", "MICHELIN", "MICHELIN 185/60/R15 ENERGY XM2+ 88H", "185", "60", "R15", 6570, origin_country="France", warranty="6 years", tire_type="Premium"),
                _raw_product(5, "arivo-ultra", "ARIVO", "ARIVO 185/60/R15 ULTRA ARZ4 84H", "185", "60", "R15", 4300, tire_type="Economy"),
            ]
        elif rim == "R15" and brand_filter == "YOKOHAMA":
            products = [
                _raw_product(1, "yoko-bluearth", "YOKOHAMA", "YOKOHAMA 185/60/R15 BLUEARTH ES32 84H", "185", "60", "R15", 4815),
                _raw_product(2, "yoko-ae01", "YOKOHAMA", "YOKOHAMA 175/55/R15 BLUEARTH AE01 77V", "175", "55", "R15", 4695),
            ]
        elif rim == "R15":
            products = [
                _raw_product(
                    3,
                    "atlas-force",
                    "ATLAS",
                    "ATLAS 185/60/R15 FORCE HP 84H",
                    "185",
                    "60",
                    "R15",
                    3040,
                    origin_country="China",
                    warranty="1 year",
                    tire_type="Budget",
                ),
                _raw_product(
                    5,
                    "westlake-r15",
                    "WESTLAKE",
                    "WESTLAKE 185/60/R15 RP18 84H",
                    "185",
                    "60",
                    "R15",
                    3600,
                    origin_country="China",
                    warranty="2 years",
                    tire_type="Economy",
                ),
                _raw_product(
                    6,
                    "arivo-r15",
                    "ARIVO",
                    "ARIVO 185/60/R15 ULTRA ARZ4 84H",
                    "185",
                    "60",
                    "R15",
                    4300,
                    origin_country="UK",
                    warranty="2 years",
                    tire_type="Mid Range",
                ),
                _raw_product(
                    4,
                    "michelin-xm2",
                    "MICHELIN",
                    "MICHELIN 185/60/R15 ENERGY XM2+ 88H",
                    "185",
                    "60",
                    "R15",
                    6570,
                    origin_country="France",
                    warranty="6 years",
                    tire_type="Premium",
                    installments=[{"bank_name": "BPI", "months_to_pay": 6, "percent_interest": 0}],
                ),
                _raw_product(
                    1,
                    "yoko-bluearth",
                    "YOKOHAMA",
                    "YOKOHAMA 185/60/R15 BLUEARTH ES32 84H",
                    "185",
                    "60",
                    "R15",
                    4815,
                    origin_country="Japan",
                    warranty="5 years",
                    tire_type="Premium",
                ),
            ]
        elif brand_filter == "MICHELIN--YOKOHAMA":
            products = [_raw_product(4, "michelin-xm2", "MICHELIN", "MICHELIN 185/60/R15 ENERGY XM2+ 88H", "185", "60", "R15", 6570)]
        elif brand_filter == "MICHELIN":
            products = [_raw_product(4, "michelin-xm2", "MICHELIN", "MICHELIN 185/60/R15 ENERGY XM2+ 88H", "185", "60", "R15", 6570)]
        elif brand_filter == "YOKOHAMA":
            products = [_raw_product(1, "yoko-bluearth", "YOKOHAMA", "YOKOHAMA 185/60/R15 BLUEARTH ES32 84H", "185", "60", "R15", 4815)]
        elif brand_filter == "BFGOODRICH":
            products = [
                _raw_product(
                    100,
                    "bfg-advantage",
                    "BFGOODRICH",
                    "BFGOODRICH 175/65/R14 ADVANTAGE TOURING 82H",
                    "175",
                    "65",
                    "R14",
                    4165,
                    promo=3165,
                    sale_tag=1,
                    product_discount={
                        "name": "BFG Promo",
                        "description": "1000 OFF",
                        "total_discount": 1000,
                        "status_id": 1,
                    },
                )
            ]
        elif rim == "R16":
            products = [
                _raw_product(20, "apollo-promo", "APOLLO", "APOLLO 205/55/R16 ALNAC 4G 91V", "205", "55", "R16", 5000, promo_tag=1),
                _raw_product(21, "other-promo-tag", "OTHER", "OTHER 205/55/R16 TAGGED 91V", "205", "55", "R16", 4500, promo_tag=1),
            ]
        elif rim == "ZR21":
            products = [
                _raw_product(30, "michelin-ev", "MICHELIN", "MICHELIN 265/35/ZR21 PILOT SPORT EV 101Y", "265", "35", "ZR21", 41000, ev_tire=1),
                _raw_product(31, "michelin-non-ev", "MICHELIN", "MICHELIN 265/35/ZR21 PILOT SPORT 4 S 101Y", "265", "35", "ZR21", 39000, ev_tire=0),
            ]
        elif rim == "R18":
            products = [
                _raw_product(40, "tier-one", "GUARANTEE", "GUARANTEE 235/60/R18 ONE 103V", "235", "60", "R18", 8000, is_gulong_guarantee=1, pre_order=1),
                _raw_product(41, "tier-two", "GUARANTEE", "GUARANTEE 235/60/R18 TWO 103V", "235", "60", "R18", 7000, is_gulong_guarantee=2),
                _raw_product(42, "no-guarantee", "NOGUARANTEE", "NOGUARANTEE 235/60/R18 BASE 103V", "235", "60", "R18", 6000, is_gulong_guarantee=0),
            ]
        elif rim == "R19":
            products = [
                _raw_product(50, "inactive-product", "INACTIVE", "INACTIVE 245/45/R19 BAD 98W", "245", "45", "R19", 5000, status_id=1),
                _raw_product(51, "active-product", "ACTIVE", "ACTIVE 245/45/R19 GOOD 98W", "245", "45", "R19", 5500, status_id=0),
            ]
        elif rim == "R15C" and section == "195":
            products = [
                _raw_product(60, "commercial-r15c", "COMMERCIAL", "COMMERCIAL 195/R15C VAN 106/104R", "195", "", "R15C", 4800),
            ]
        elif rim == "R14C" and section == "195" and aspect == "80":
            products = [
                _raw_product(61, "commercial-r14c-80", "COMMERCIAL", "COMMERCIAL 195/80/R14C VAN 106/104R", "195", "80", "R14C", 4900),
            ]
        elif rim == "R14C" and section == "195":
            products = [
                _raw_product(60, "commercial-r14c-implicit", "COMMERCIAL", "COMMERCIAL 195/R14C VAN 106/104R", "195", "", "R14C", 4800),
                _raw_product(61, "commercial-r14c-80", "COMMERCIAL", "COMMERCIAL 195/80/R14C VAN 106/104R", "195", "80", "R14C", 4900),
                _raw_product(62, "commercial-r14c-70", "COMMERCIAL", "COMMERCIAL 195/70/R14C VAN 102/100R", "195", "70", "R14C", 4000),
            ]
        elif rim == "15" and section == "7.50":
            products = [
                _raw_product(70, "legacy-750-15", "APOLLO", "APOLLO 7.50-15 AMAR GOLD 110/105L", "7.50", "", "15", 8000),
            ]
        elif rim == "20" and section == "8.25":
            products = [
                _raw_product(71, "legacy-825-20", "APOLLO", "APOLLO 8.25-20 AMAR DELUXE 137/132J", "8.25", "", "20", 14645),
            ]
        elif not any([brand_filter, rim, section, aspect]):
            products = [
                _raw_product(80, "shop-pilot-sport", "MICHELIN", "MICHELIN 245/35/ZR18 PILOT SPORT 4 ZP 92Y XL TL", "245", "35", "ZR18", 39000),
            ]
        return _category_payload(products)

    def get_json(self, path):
        self.get_calls.append(path)
        if path == "/product_list":
            return [
                _raw_product(10, "yoko-geolandar", "YOKOHAMA", "YOKOHAMA 265/50/R20 GEOLANDAR A/T G015 111W", "265", "50", "R20", 13350),
                _raw_product(11, "michelin-primacy", "MICHELIN", "MICHELIN 195/60/R15 PRIMACY 4 ST 92V", "195", "60", "R15", 7525),
                _raw_product(12, "bfg-km3", "BFGOODRICH", "BFGOODRICH 265/70/R17 MUD-TERRAIN T/A KM3 121Q", "265", "70", "R17", 19500),
                _raw_product(13, "atlas-highway", "ATLAS", "ATLAS 265/70/R17 FORCE HP 115T", "265", "70", "R17", 6000),
                _raw_product(14, "trn123-touring", "TEST", "TEST 215/55/R17 TOURING 94V", "215", "55", "R17", 5000),
                _raw_product(15, "catalog-yoko-bluearth", "YOKOHAMA", "YOKOHAMA 185/60/R15 BLUEARTH ES32 84H", "185", "60", "R15", 4815, tire_type="Premium"),
                _raw_product(16, "catalog-michelin-xm2", "MICHELIN", "MICHELIN 185/60/R15 ENERGY XM2+ 88H", "185", "60", "R15", 6570, tire_type="Premium"),
                _raw_product(17, "catalog-arivo-ultra", "ARIVO", "ARIVO 185/60/R15 ULTRA ARZ4 84H", "185", "60", "R15", 4300, tire_type="Economy"),
            ]
        if path == "/promo_brands":
            return [{"brand": "APOLLO"}]
        return []


class PromoBrandAuthorityHTTPClient(FakeHTTPClient):
    def post_json(self, path, *, params=None, json_data=None):
        params = params or {}
        brand_filter = str(params.get("b") or "")
        rim = str(params.get("rim_size") or "")
        section = str(params.get("section_width") or "")
        aspect = str(params.get("aspect_ratio") or "")
        if brand_filter == "APOLLO" and rim == "R16" and section == "215" and aspect == "55":
            return _category_payload(
                [
                    _raw_product(
                        8265,
                        "apollo-215-55-r16-alnac-4g",
                        "APOLLO",
                        "APOLLO 215/55/R16 ALNAC 4G",
                        "215",
                        "55",
                        "R16",
                        7105,
                        promo=5330,
                        promo_tag=1,
                        sale_tag=0,
                        tire_type="Mid Range",
                    )
                ]
            )
        if brand_filter == "VREDESTEIN" and rim == "R14" and section == "175" and aspect == "65":
            return _category_payload(
                [
                    _raw_product(
                        10724,
                        "vredestein-175-65-r14-t-trac-2-86t+1",
                        "VREDESTEIN",
                        "VREDESTEIN 175/65/R14 T-TRAC 2 86T",
                        "175",
                        "65",
                        "R14",
                        4280,
                        promo=3210,
                        promo_tag=1,
                        sale_tag=0,
                        tire_type="Mid Range",
                    )
                ]
            )
        if brand_filter == "MICHELIN" and rim == "R14" and section == "175" and aspect == "65":
            return _category_payload(
                [
                    _raw_product(
                        7420,
                        "michelin-175-65-r14-energy-xm2",
                        "MICHELIN",
                        "MICHELIN 175/65/R14 ENERGY XM2+",
                        "175",
                        "65",
                        "R14",
                        6490,
                        promo=5490,
                        sale_tag=1,
                        promo_tag=0,
                        warranty="6 years",
                        tire_type="Premium",
                    )
                ]
            )
        if brand_filter == "MICHELIN" and rim == "R18" and section == "225" and aspect == "60":
            return _category_payload(
                [
                    _raw_product(
                        8024,
                        "michelin-225-60-r18-primacy-suv",
                        "MICHELIN",
                        "MICHELIN 225/60/R18 PRIMACY SUV+ 100H",
                        "225",
                        "60",
                        "R18",
                        15050,
                        promo=14050,
                        sale_tag=1,
                        promo_tag=0,
                        warranty="6 years",
                        tire_type="Premium",
                    )
                ]
            )
        if brand_filter == "MICHELIN" and rim == "R16" and section == "215" and aspect == "55":
            return _category_payload(
                [
                    _raw_product(
                        11430,
                        "michelin-215-55-r16-primacy-5-97w",
                        "MICHELIN",
                        "MICHELIN 215/55/R16 PRIMACY 5 97W XL TL",
                        "215",
                        "55",
                        "R16",
                        11990,
                        promo=10990,
                        sale_tag=1,
                        promo_tag=0,
                        tire_type="Premium",
                    )
                ]
            )
        return super().post_json(path, params=params, json_data=json_data)

    def get_json(self, path):
        if path == "/promo_brands":
            return [{"brand": "APOLLO"}, {"brand": "MICHELIN"}, {"brand": "VREDESTEIN"}]
        return super().get_json(path)


class PromoUpsellHTTPClient(FakeHTTPClient):
    def post_json(self, path, *, params=None, json_data=None):
        self.post_calls.append({"path": path, "params": dict(params or {})})
        params = params or {}
        if str(params.get("rim_size") or "") != "R16":
            return super().post_json(path, params=params, json_data=json_data)
        return _category_payload(
            [
                _raw_product(
                    90,
                    "apollo-budget-promo",
                    "APOLLO",
                    "APOLLO 205/55/R16 ALNAC 4G 91V",
                    "205",
                    "55",
                    "R16",
                    5000,
                    promo_tag=1,
                    tire_type="Mid Range",
                ),
                _raw_product(
                    91,
                    "vredestein-budget-promo",
                    "VREDESTEIN",
                    "VREDESTEIN 205/55/R16 T-TRAC 2 91V",
                    "205",
                    "55",
                    "R16",
                    4500,
                    promo_tag=1,
                    tire_type="Mid Range",
                ),
                _raw_product(
                    92,
                    "michelin-upsell-promo",
                    "MICHELIN",
                    "MICHELIN 205/55/R16 PRIMACY 5 91V",
                    "205",
                    "55",
                    "R16",
                    7000,
                    promo_tag=1,
                    tire_type="Premium",
                ),
                _raw_product(
                    93,
                    "other-non-promo-brand",
                    "OTHER",
                    "OTHER 205/55/R16 TAGGED 91V",
                    "205",
                    "55",
                    "R16",
                    3500,
                    promo_tag=1,
                    tire_type="Budget",
                ),
            ]
        )

    def get_json(self, path):
        self.get_calls.append(path)
        if path == "/promo_brands":
            return [{"brand": "APOLLO"}, {"brand": "VREDESTEIN"}, {"brand": "MICHELIN"}]
        return []


class ExactSizeWithSameRimPromoHTTPClient(FakeHTTPClient):
    def post_json(self, path, *, params=None, json_data=None):
        self.post_calls.append({"path": path, "params": dict(params or {})})
        params = params or {}
        rim = str(params.get("rim_size") or "")
        section = str(params.get("section_width") or "")
        aspect = str(params.get("aspect_ratio") or "")
        if rim != "R17":
            return super().post_json(path, params=params, json_data=json_data)
        if section == "205" and aspect == "45":
            return _category_payload(
                [
                    _raw_product(200, "fronway-205-45-r17", "FRONWAY", "FRONWAY 205/45/R17 EURUS 08 88W", "205", "45", "R17", 3010, tire_type="Budget"),
                    _raw_product(201, "linglong-205-45-r17", "LINGLONG", "LINGLONG 205/45/R17 SPORT MASTER 88Y", "205", "45", "R17", 3480, tire_type="Budget"),
                    _raw_product(202, "yoko-205-45-r17-promo", "YOKOHAMA", "YOKOHAMA 205/45/R17 ADVAN FLEVA V701 88W", "205", "45", "R17", 6645, promo_tag=1, tire_type="Premium"),
                ]
            )
        return _category_payload(
            [
                _raw_product(203, "bfg-215-45-r17-promo", "BFGOODRICH", "BFGOODRICH 215/45/R17 ADVANTAGE TOURING 91V", "215", "45", "R17", 5250, promo_tag=1, tire_type="Mid Range"),
                _raw_product(204, "vred-205-50-r17-promo", "VREDESTEIN", "VREDESTEIN 205/50/R17 ULTRAC I", "205", "50", "R17", 7565, promo_tag=1, tire_type="Mid Range"),
            ]
        )

    def get_json(self, path):
        self.get_calls.append(path)
        if path == "/promo_brands":
            return [{"brand": "BFGOODRICH"}, {"brand": "VREDESTEIN"}, {"brand": "YOKOHAMA"}]
        return super().get_json(path)


class ExactSizeMixedPromoHTTPClient(FakeHTTPClient):
    def post_json(self, path, *, params=None, json_data=None):
        self.post_calls.append({"path": path, "params": dict(params or {})})
        params = params or {}
        rim = str(params.get("rim_size") or "")
        section = str(params.get("section_width") or "")
        aspect = str(params.get("aspect_ratio") or "")
        if rim == "R18" and section == "215" and aspect == "50":
            return _category_payload(
                [
                    _raw_product(
                        210,
                        "toyo-215-50-r18",
                        "TOYO",
                        "TOYO 215/50/R18 PXR40 92V",
                        "215",
                        "50",
                        "R18",
                        14000,
                        tire_type="Mid Range",
                    ),
                    _raw_product(
                        211,
                        "michelin-215-50-r18-b3g1",
                        "MICHELIN",
                        "MICHELIN 215/50/R18 PRIMACY SUV+ 92V TL",
                        "215",
                        "50",
                        "R18",
                        12040,
                        promo_tag=1,
                        tire_type="Premium",
                    ),
                ]
            )
        return super().post_json(path, params=params, json_data=json_data)

    def get_json(self, path):
        self.get_calls.append(path)
        if path == "/promo_brands":
            return [{"brand": "MICHELIN"}]
        return super().get_json(path)


class NittoTerrainMismatchHTTPClient(FakeHTTPClient):
    """Return exact-size Nitto rows that do not satisfy an A/T filter."""

    def _products(self):
        return [
            _raw_product(
                301,
                "nitto-265-50-r20-420sd",
                "NITTO",
                "NITTO 265/50/R20 420SD HP 111V",
                "265",
                "50",
                "R20",
                13046.50,
                default_image="https://gulongph.sgp1.digitaloceanspaces.com/test/nitto-420sd.webp",
            ),
            _raw_product(
                302,
                "nitto-265-50-r20-421q",
                "NITTO",
                "NITTO 265/50/R20 421Q HP 111V",
                "265",
                "50",
                "R20",
                15893.45,
                default_image="https://gulongph.sgp1.digitaloceanspaces.com/test/nitto-421q.webp",
            ),
            _raw_product(
                303,
                "nitto-265-50-r20-terra",
                "NITTO",
                "NITTO 265/50/R20 TERRA GRAPPLER NTGA2 111S",
                "265",
                "50",
                "R20",
                17915.90,
                default_image="https://gulongph.sgp1.digitaloceanspaces.com/test/nitto-terra.webp",
            ),
            _raw_product(
                304,
                "other-265-50-r20-at",
                "OTHER",
                "OTHER 265/50/R20 TRAIL A/T 111S",
                "265",
                "50",
                "R20",
                12000,
                pattern="TRAIL A/T",
                default_image="https://gulongph.sgp1.digitaloceanspaces.com/test/other-at.webp",
            ),
        ]

    def post_json(self, path, *, params=None, json_data=None):
        params = params or {}
        if str(params.get("rim_size") or "") not in {"R20", "ZR20"}:
            return super().post_json(path, params=params, json_data=json_data)
        self.post_calls.append({"path": path, "params": dict(params)})
        products = self._products()
        brand_filter = str(params.get("b") or "").strip().upper()
        if brand_filter:
            allowed = set(brand_filter.split("--"))
            products = [
                product
                for product in products
                if str(product.get("make") or "").upper() in allowed
            ]
        section = str(params.get("section_width") or "").strip()
        aspect = str(params.get("aspect_ratio") or "").strip()
        if section:
            products = [
                product
                for product in products
                if str(product.get("section_width") or "") == section
            ]
        if aspect:
            products = [
                product
                for product in products
                if str(product.get("aspect_ratio") or "") == aspect
            ]
        return _category_payload(products)

    def get_json(self, path):
        self.get_calls.append(path)
        if path == "/product_list":
            return self._products()
        return super().get_json(path)


class VisibilityDenylistHTTPClient(FakeHTTPClient):
    def get_json(self, path):
        self.get_calls.append(path)
        if path == "/product_list":
            return [
                _raw_product(15, "catalog-yoko-bluearth", "YOKOHAMA", "YOKOHAMA 185/60/R15 BLUEARTH ES32 84H", "185", "60", "R15", 4815, tire_type="Premium"),
                _raw_product(16, "catalog-michelin-xm2", "MICHELIN", "MICHELIN 185/60/R15 ENERGY XM2+ 88H", "185", "60", "R15", 6570, tire_type="Premium"),
                _raw_product(14046, "chengshan-185-60-r15-csc-802-84h", "CHENGSHAN", "CHENGSHAN 185/60/R15 CSC-802 84H", "185", "60", "R15", 2500, tire_type="Budget"),
            ]
        return super().get_json(path)


class PresentationPriorityHTTPClient(FakeHTTPClient):
    def post_json(self, path, *, params=None, json_data=None):
        self.post_calls.append({"path": path, "params": dict(params or {})})
        params = params or {}
        if str(params.get("rim_size") or "") != "R20":
            return super().post_json(path, params=params, json_data=json_data)
        return _category_payload(
            [
                _raw_product(
                    100,
                    "cheap-budget",
                    "CHEAPCO",
                    "CHEAPCO 275/55/R20 STANDARD 117V",
                    "275",
                    "55",
                    "R20",
                    3000,
                    tire_type="Budget",
                ),
                _raw_product(
                    101,
                    "promo-budget",
                    "APOLLO",
                    "APOLLO 275/55/R20 PROMO 117V",
                    "275",
                    "55",
                    "R20",
                    3400,
                    promo_tag=1,
                    tire_type="Budget",
                ),
                _raw_product(
                    102,
                    "preorder-economy-promo",
                    "VREDESTEIN",
                    "VREDESTEIN 275/55/R20 PREORDER 117V",
                    "275",
                    "55",
                    "R20",
                    3300,
                    promo_tag=1,
                    pre_order=1,
                    tire_type="Economy",
                ),
                _raw_product(
                    103,
                    "stock-economy",
                    "ARIVO",
                    "ARIVO 275/55/R20 STOCK 117V",
                    "275",
                    "55",
                    "R20",
                    3600,
                    tire_type="Economy",
                ),
                _raw_product(
                    104,
                    "preorder-mid-promo",
                    "MICHELIN",
                    "MICHELIN 275/55/R20 PREORDER 117V",
                    "275",
                    "55",
                    "R20",
                    5200,
                    promo_tag=1,
                    pre_order=1,
                    tire_type="Mid Range",
                ),
                _raw_product(
                    105,
                    "premium-stock",
                    "YOKOHAMA",
                    "YOKOHAMA 275/55/R20 STOCK 117V",
                    "275",
                    "55",
                    "R20",
                    7200,
                    tire_type="Premium",
                ),
            ]
        )

    def get_json(self, path):
        self.get_calls.append(path)
        if path == "/promo_brands":
            return [{"brand": "APOLLO"}, {"brand": "VREDESTEIN"}, {"brand": "MICHELIN"}]
        return []


class MichelinPilotRimHTTPClient(FakeHTTPClient):
    def __init__(self, *, include_same_size_alternatives=True):
        super().__init__()
        self.include_same_size_alternatives = include_same_size_alternatives

    def post_json(self, path, *, params=None, json_data=None):
        self.post_calls.append({"path": path, "params": dict(params or {})})
        params = params or {}
        rim = str(params.get("rim_size") or "")
        brand = str(params.get("b") or "")
        if brand == "MICHELIN":
            if rim and rim != "R15":
                return _category_payload([])
            return _category_payload(
                [
                    _raw_product(
                        200,
                        "michelin-pilot-r15",
                        "MICHELIN",
                        "MICHELIN 195/50/R15 PILOT SPORT 3 82V",
                        "195",
                        "50",
                        "R15",
                        9360,
                        promo_tag=1,
                    )
                ]
            )
        if rim == "R15":
            return _category_payload(self._catalog_products())
        return super().post_json(path, params=params, json_data=json_data)

    def get_json(self, path):
        self.get_calls.append(path)
        if path == "/product_list":
            return self._catalog_products()
        if path == "/promo_brands":
            return [{"brand": "MICHELIN"}]
        return []

    def _catalog_products(self):
        products = [
            _raw_product(
                200,
                "michelin-pilot-r15",
                "MICHELIN",
                "MICHELIN 195/50/R15 PILOT SPORT 3 82V",
                "195",
                "50",
                "R15",
                9360,
                promo_tag=1,
            ),
            _raw_product(
                203,
                "deestone-other-r15",
                "DEESTONE",
                "DEESTONE 185/60/R15 TOURER 84H",
                "185",
                "60",
                "R15",
                3100,
                tire_type="Economy",
            ),
        ]
        if self.include_same_size_alternatives:
            products.extend(
                [
                    _raw_product(
                        201,
                        "yokohama-same-size-r15",
                        "YOKOHAMA",
                        "YOKOHAMA 195/50/R15 ADVAN FLEVA 82V",
                        "195",
                        "50",
                        "R15",
                        6200,
                    ),
                    _raw_product(
                        202,
                        "bfg-same-size-r15",
                        "BFGOODRICH",
                        "BFGOODRICH 195/50/R15 ADVANTAGE TOURING 82V",
                        "195",
                        "50",
                        "R15",
                        4700,
                        tire_type="Mid Range",
                    ),
                ]
            )
        return products


def _raw_product(
    product_id,
    slug,
    make,
    model,
    section,
    aspect,
    rim,
    srp,
    *,
    status_id=0,
    promo_tag=0,
    ev_tire=0,
    is_gulong_guarantee=0,
    pre_order=0,
    origin_country="Japan",
    warranty="5 years",
    tire_type="Premium",
    pattern=None,
    description=None,
    features=None,
    installments=None,
    dot_sku="2024",
    promo=None,
    sale_tag=0,
    product_discount=None,
    warranty_year=None,
    default_product_banner=None,
    banner=None,
    product_promo=None,
    default_image=None,
):
    return {
        "id": product_id,
        "slug": slug,
        "make": make,
        "model": model,
        "section_width": section,
        "aspect_ratio": aspect,
        "rim_size": rim,
        "srp": srp,
        "promo": promo,
        "sale_tag": sale_tag,
        "product_discount": product_discount,
        "banner": banner,
        "product_promo": product_promo,
        "default_image": default_image,
        "origin_country": origin_country,
        "warranty": warranty,
        "warranty_year": warranty_year,
        "default_product_banner": default_product_banner,
        "ev_tire": ev_tire,
        "status_id": status_id,
        "activity": 1,
        "promo_tag": promo_tag,
        "pre_order": pre_order,
        "is_gulong_guarantee": is_gulong_guarantee,
        "tire_type": tire_type,
        "pattern": pattern,
        "description": description,
        "features": features,
        "installments": installments or [],
        "DOT_SKU": dot_sku,
    }


def _category_payload(products):
    grouped = {}
    for product in products:
        category = product.get("tire_type") or "Premium"
        grouped.setdefault(category, []).append(product)
    return [
        {"id": index + 1, "name": category, "slug": f"{category.lower().replace(' ', '-')}-tires", "products": rows}
        for index, (category, rows) in enumerate(grouped.items())
    ]


def test_exact_size_brand_result_is_ok():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "section_width": "185",
            "aspect_ratio": "60",
            "rim_size": "15",
            "brands": ["Yokohama"],
            "model_or_pattern": "BlueEarth",
            "budget_max": 5000,
            "budget_scope": "per_tire",
            "top_k": 3,
        }
    )

    assert result["status"] == "ok"
    assert result["result_level"] == "exact"
    assert result["query_basis"]["normalized_filters"]["brands"] == ["YOKOHAMA"]
    assert result["best_products"][0]["brand"] == "YOKOHAMA"
    assert "brand" in result["best_products"][0]["match"]["passed_filters"]
    assert "rim_size" in result["best_products"][0]["match"]["passed_filters"]


def test_product_cards_for_size_only_prioritize_price_categories():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run({"rim_size": "R15", "top_k": 4})

    cards = result["product_cards"]
    assert [card["category"] for card in cards] == ["Budget", "Economy", "Mid Range", "Premium"]
    assert result["presentation_strategy"]["mode"] == "size_category_mix"
    assert "[BUDGET]" in cards[0]["card_text"]
    assert all("🗓️ DOT: 2024" in card["card_text"] for card in cards)
    assert all("🔗 https://gulong.ph/product/" in card["card_text"] for card in cards)
    assert all("Category:" not in card["card_text"] for card in cards)
    assert all("Model:" not in card["card_text"] for card in cards)


def test_general_size_inquiry_expands_to_four_cards_when_tier_spread_exists():
    class FourTierFullSizeHTTPClient(FakeHTTPClient):
        def post_json(self, path, *, params=None, json_data=None):
            params = params or {}
            if (
                str(params.get("section_width") or "") == "275"
                and str(params.get("aspect_ratio") or "") == "55"
                and str(params.get("rim_size") or "") == "R20"
            ):
                return _category_payload(
                    [
                        _raw_product(301, "fronway-r20", "FRONWAY", "FRONWAY 275/55/R20 ROCKBLADE AT II 117/S XL", "275", "55", "R20", 6600, tire_type="Budget"),
                        _raw_product(302, "nankang-r20", "NANKANG", "NANKANG 275/55/R20 SP-7 117H", "275", "55", "R20", 9000, tire_type="Economy"),
                        _raw_product(303, "vredestein-r20", "VREDESTEIN", "VREDESTEIN 275/55/R20 PINZA AT", "275", "55", "R20", 8475, tire_type="Mid Range"),
                        _raw_product(304, "yokohama-r20", "YOKOHAMA", "YOKOHAMA 275/55/R20 GEOLANDAR A/T 4 G018 117H", "275", "55", "R20", 12000, tire_type="Premium"),
                    ]
                )
            return super().post_json(path, params=params, json_data=json_data)

    runner = ProductSearchRunner(http_client=FourTierFullSizeHTTPClient(), max_api_calls=8)
    result = runner.run({"section_width": "275", "aspect_ratio": "55", "rim_size": "R20", "top_k": 3})

    cards = result["product_cards"]
    assert len(cards) == 4
    assert [card["category"] for card in cards] == ["Premium", "Mid Range", "Economy", "Budget"]


def test_product_search_splits_no_aspect_commercial_tire_size_arg():
    class NoAspectCommercialHTTPClient(FakeHTTPClient):
        def post_json(self, path, *, params=None, json_data=None):
            self.post_calls.append({"path": path, "params": dict(params or {})})
            params = params or {}
            if str(params.get("section_width") or "") == "185" and str(params.get("rim_size") or "") == "R14":
                return _category_payload(
                    [
                        _raw_product(
                            401,
                            "westlake-185-r14",
                            "WESTLAKE",
                            "WESTLAKE 185/R14 SC328",
                            "185",
                            "",
                            "R14",
                            3433.80,
                            tire_type="Budget",
                        )
                    ]
                )
            return []

    runner = ProductSearchRunner(http_client=NoAspectCommercialHTTPClient(), max_api_calls=4)
    result = runner.run({"tire_size": "185R14", "top_k": 3})

    assert result["status"] == "ok"
    assert result["query_basis"]["normalized_filters"]["section_width"] == "185"
    assert result["query_basis"]["normalized_filters"]["rim_size"] == "R14"
    assert result["product_cards"][0]["brand"] == "WESTLAKE"
    assert any(call["params"].get("section_width") == "185" and call["params"].get("rim_size") == "R14" for call in runner._http.post_calls)


def test_preferred_brands_prioritize_presentation_without_hard_filtering_pool():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run({"rim_size": "R15", "preferred_brands": ["Yokohama", "Michelin", "Bridgestone"], "top_k": 4})

    assert result["query_basis"]["normalized_filters"]["preferred_brands"] == ["YOKOHAMA", "MICHELIN", "BRIDGESTONE"]
    assert result["result_pool_summary"]["exact"] > 0
    brands = [card["brand"] for card in result["product_cards"]]
    assert brands[:2] == ["YOKOHAMA", "MICHELIN"]
    assert "preferred brand option" in {card["why_shown"] for card in result["product_cards"]}
    assert result["requested_brand_status"] == {"requested": [], "matched": [], "missing": []}
    assert result["preferred_brand_status"]["requested"] == ["BRIDGESTONE", "MICHELIN", "YOKOHAMA"]
    assert result["preferred_brand_status"]["matched"] == ["MICHELIN", "YOKOHAMA"]
    assert result["preferred_brand_status"]["missing"] == ["BRIDGESTONE"]


def test_preferred_brand_conflict_is_reported_without_overriding_latest_category_filter():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "rim_size": "R15",
            "preferred_brands": ["Michelin"],
            "tire_categories": ["Budget"],
            "top_k": 3,
        }
    )

    brands = [card["brand"] for card in result["product_cards"]]
    assert "MICHELIN" not in brands
    status = result["preferred_brand_presentation_status"]
    assert status["matched"] == ["MICHELIN"]
    assert status["presented"] == []
    assert status["not_presented"] == ["MICHELIN"]
    assert status["not_presented_reasons"][0]["missed_filters"] == ["tire_category"]


def test_required_brands_alias_prioritizes_requested_brand_when_available():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run({"rim_size": "R15", "required_brands": ["Yokohama"], "top_k": 3})

    assert result["query_basis"]["normalized_filters"]["brands"] == ["YOKOHAMA"]
    assert result["query_basis"]["normalized_filters"]["brand_match_mode"] == "prefer"
    assert result["best_products"][0]["brand"] == "YOKOHAMA"
    assert "brand" in result["best_products"][0]["match"]["passed_filters"]
    assert {
        card["brand"]
        for card in result["product_cards"]
    } == {"YOKOHAMA"}


def test_excluded_brand_origin_and_category_filters_are_applied():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "rim_size": "R15",
            "excluded_brands": ["Michelin"],
            "excluded_origins": ["China"],
            "excluded_tire_categories": ["Premium"],
            "top_k": 6,
        }
    )

    filters = result["query_basis"]["normalized_filters"]
    assert filters["excluded_brands"] == ["MICHELIN"]
    assert filters["excluded_origins"] == ["CHINA"]
    assert filters["excluded_tire_categories"] == ["PREMIUM"]
    cards = result["product_cards"]
    assert cards
    assert all(card["brand"] != "MICHELIN" for card in cards)
    assert all(card["category"] != "Premium" for card in cards)


def test_excluded_origin_uses_known_brand_origin_when_catalog_origin_is_blank():
    class BlankOriginHTTPClient:
        def post_json(self, path, *, params=None, json_data=None):
            return _category_payload(
                [
                    _raw_product(
                        1,
                        "linglong-r14",
                        "LINGLONG",
                        "LINGLONG 175/65/R14 COMFORT MASTER 82H",
                        "175",
                        "65",
                        "R14",
                        2200,
                        origin_country=None,
                        tire_type="Budget",
                    ),
                    _raw_product(
                        2,
                        "deestone-r14",
                        "DEESTONE",
                        "DEESTONE 175/65/R14 NAKARA R201 82H",
                        "175",
                        "65",
                        "R14",
                        2600,
                        origin_country="Thailand",
                        tire_type="Economy",
                    ),
                ]
            )

        def get_json(self, path, *, params=None):
            return []

    runner = ProductSearchRunner(http_client=BlankOriginHTTPClient(), max_api_calls=2)
    result = runner.run({"section_width": "175", "aspect_ratio": "65", "rim_size": "R14", "excluded_origins": ["China"]})

    brands = [card["brand"] for card in result["product_cards"]]
    assert "LINGLONG" not in brands
    assert "DEESTONE" in brands


def test_product_cards_prioritize_promos_but_deprioritize_pre_orders():
    runner = ProductSearchRunner(http_client=PresentationPriorityHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R20", "top_k": 4})

    cards = result["product_cards"]
    by_category = {card["category"]: card for card in cards}
    assert by_category["Budget"]["slug"] == "promo-budget"
    assert by_category["Economy"]["slug"] == "stock-economy"
    assert by_category["Mid Range"]["slug"] == "preorder-mid-promo"

    presented = {product["slug"]: product for product in result["presented_products"]}
    assert presented["promo-budget"]["buy3get1_eligible"] is True
    assert presented["stock-economy"]["pre_order"] is False
    assert presented["preorder-mid-promo"]["pre_order"] is True


def test_product_cards_for_size_brand_fetch_other_brand_options():
    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=8)
    result = runner.run(
        {
            "section_width": "185",
            "aspect_ratio": "60",
            "rim_size": "15",
            "brands": ["Yokohama"],
            "soft_preferences": ["compare alternatives"],
            "top_k": 4,
        }
    )

    cards = result["product_cards"]
    brands = [card["brand"] for card in cards]
    assert brands[0] == "YOKOHAMA"
    assert "MICHELIN" in brands
    assert any(brand not in {"YOKOHAMA"} for brand in brands)
    assert "presentation_catalog_alternatives" in {attempt["label"] for attempt in result["attempted_queries"]}
    assert result["presentation_strategy"]["mode"] == "size_brand_with_alternatives"


def test_premium_category_cards_prefer_michelin_over_yokohama_when_brand_unspecified():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "section_width": "185",
            "aspect_ratio": "60",
            "rim_size": "15",
            "tire_categories": ["Premium"],
            "top_k": 4,
        }
    )

    brands = [card["brand"] for card in result["product_cards"]]
    assert brands[:2] == ["MICHELIN", "YOKOHAMA"]
    assert result["product_cards"][0]["sku_model"] == "MICHELIN 185/60/R15 ENERGY XM2+ 88H"


def test_premium_category_michelin_priority_does_not_override_requested_yokohama():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "section_width": "185",
            "aspect_ratio": "60",
            "rim_size": "15",
            "brands": ["Yokohama"],
            "tire_categories": ["Premium"],
            "top_k": 4,
        }
    )

    assert result["product_cards"][0]["brand"] == "YOKOHAMA"


def test_premium_category_michelin_priority_overrides_soft_preferred_brand_order():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "section_width": "185",
            "aspect_ratio": "60",
            "rim_size": "15",
            "preferred_brands": ["Yokohama", "Michelin"],
            "tire_categories": ["Premium"],
            "top_k": 4,
        }
    )

    brands = [card["brand"] for card in result["product_cards"]]
    assert brands[:2] == ["MICHELIN", "YOKOHAMA"]


def test_product_cards_exclude_configured_hidden_visibility_products():
    ProductSearchRunner.clear_catalog_cache()
    client = VisibilityDenylistHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=8)
    result = runner.run(
        {
            "section_width": "185",
            "aspect_ratio": "60",
            "rim_size": "15",
            "brands": ["Yokohama"],
            "soft_preferences": ["compare alternatives"],
            "top_k": 4,
        }
    )

    brands = [card["brand"] for card in result["product_cards"]]
    assert "YOKOHAMA" in brands
    assert "MICHELIN" in brands
    assert "CHENGSHAN" not in brands
    assert result["visibility_filter"]["filtered_count"] == 1
    assert result["visibility_filter"]["filtered_slugs_sample"] == ["chengshan-185-60-r15-csc-802-84h"]
    assert result["query_basis"]["visibility_filter"]["applied"] is True


def test_product_cards_allow_non_denylisted_same_brand_products():
    runner = ProductSearchRunner(
        http_client=VisibilityDenylistHTTPClient(),
        max_api_calls=8,
        visibility_denylist={"hidden_product_slugs": ["not-this-product"]},
    )
    result = runner.run(
        {
            "section_width": "185",
            "aspect_ratio": "60",
            "rim_size": "15",
            "brands": ["Yokohama"],
            "soft_preferences": ["compare alternatives"],
            "top_k": 4,
        }
    )

    assert "CHENGSHAN" in [card["brand"] for card in result["product_cards"]]


def test_product_cards_for_budget_show_within_budget_options():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run({"rim_size": "R15", "budget_max": 5000, "budget_scope": "per_tire", "top_k": 4})

    assert result["presentation_strategy"]["mode"] == "budget_satisfied"
    assert len(result["product_cards"]) == 4
    for product in result["best_products"]:
        if product["item_ref"] in {card["item_ref"] for card in result["product_cards"]}:
            assert product["price"] <= 5000


def test_budget_defaults_to_total_order_scope_when_scope_omitted():
    request = ProductSearchRequest.from_mapping({"rim_size": "R15", "budget_max": 15000})
    assert request.budget_scope == "total"

    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run({"rim_size": "R15", "budget_max": 15000, "top_k": 4})

    assert result["query_basis"]["normalized_filters"]["budget_scope"] == "total"


def test_product_cards_for_unmet_budget_show_nearest_options():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run({"rim_size": "R15", "budget_max": 1000, "top_k": 3})

    assert result["presentation_strategy"]["mode"] == "nearest_budget"
    assert result["product_cards"][0]["brand"] == "ATLAS"
    assert result["product_cards"][0]["why_shown"] == "nearest option to requested budget"


def test_product_card_text_is_deterministic_and_grounded():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run({"rim_size": "R16", "brands": ["APOLLO"], "promo_only": True, "top_k": 1})

    card = result["product_cards"][0]
    assert card["category"] == "Premium"
    assert card["sku_model"] == "APOLLO 205/55/R16 ALNAC 4G 91V"
    assert "💰 PHP 5,000.00/tire | PHP 15,000.00 if for 4 tires" in card["card_text"]
    assert "🎁 Buy 3 Get 1 FREE | Save PHP 5,000.00" in card["card_text"]
    assert "🗓️ DOT: 2024" in card["card_text"]
    assert "Category:" not in card["card_text"]
    assert "Model:" not in card["card_text"]
    assert card["url"] == "https://gulong.ph/product/apollo-promo"


def test_product_card_suppresses_any_pattern_slug_mismatch_without_dropping_card():
    normalized = normalize_product(
        _raw_product(
            611,
            "michelin-195-55-r16-primacy-4-91v",
            "MICHELIN",
            "MICHELIN 195/55/R16 PRIMACY 3 ZP 91V",
            "195",
            "55",
            "R16",
            12305,
            pattern="PRIMACY 3 ZP",
        ),
        category_name="Premium",
        source="test",
        attempt_label="test",
    )

    card = render_product_cards(
        ProductSearchRequest(rim_size="R16").normalized(),
        [normalized],
    )[0]

    assert card["sku_model"] == "MICHELIN 195/55/R16 PRIMACY 3 ZP 91V"
    assert card["url"] == ""
    assert card["product_link_status"] == "suppressed_pattern_slug_mismatch"
    assert "https://gulong.ph/product/" not in card["card_text"]
    assert "🔗 -" not in card["card_text"]


def test_product_card_keeps_link_when_structured_pattern_matches_slug():
    normalized = normalize_product(
        _raw_product(
            612,
            "michelin-195-55-r16-primacy-3-zp-91v",
            "MICHELIN",
            "MICHELIN 195/55/R16 PRIMACY 3 ZP 91V",
            "195",
            "55",
            "R16",
            12305,
            pattern="PRIMACY 3 ZP",
        ),
        category_name="Premium",
        source="test",
        attempt_label="test",
    )

    card = render_product_cards(
        ProductSearchRequest(rim_size="R16").normalized(),
        [normalized],
    )[0]

    assert card["url"] == (
        "https://gulong.ph/product/michelin-195-55-r16-primacy-3-zp-91v"
    )
    assert card["product_link_status"] == "matched"
    assert card["url"] in card["card_text"]


def test_product_card_link_allows_slug_abbreviation_when_model_code_matches():
    normalized = normalize_product(
        _raw_product(
            613,
            "dunlop-195-55-r16-lm705-87v",
            "DUNLOP",
            "DUNLOP 195/55/R16 SP SPORT LM705 87V",
            "195",
            "55",
            "R16",
            6200,
            pattern="SP SPORT LM705",
        ),
        category_name="Premium",
        source="test",
        attempt_label="test",
    )

    card = render_product_cards(
        ProductSearchRequest(rim_size="R16").normalized(),
        [normalized],
    )[0]

    assert card["product_link_status"] == "matched"
    assert card["url"].endswith("/dunlop-195-55-r16-lm705-87v")


def test_product_card_includes_origin_warranty_and_tire_protection_when_available():
    product = _raw_product(
        98,
        "with-plan",
        "TEST",
        "TEST 185/60/R15 PROTECT 84H",
        "185",
        "60",
        "R15",
        4500,
        origin_country="Japan",
        warranty="5 years",
        is_gulong_guarantee=1,
    )
    normalized = normalize_product(
        product,
        category_name="Mid Range",
        source="test",
        attempt_label="test",
    )

    card = render_product_cards(ProductSearchRequest(rim_size="R15").normalized(), [normalized])[0]

    assert card["origin"] == "Japan"
    assert card["warranty"] == "5 years"
    assert card["tire_protection_plan"] == "Tire Protection Plan (1 Year)"
    assert "Origin: Japan" in card["card_text"]
    assert "Warranty: 5 years + Tire Protection Plan (1 Year)" in card["card_text"]


def test_product_card_normalizes_only_bare_numeric_warranty_years():
    cases = [
        ("5", "5 years"),
        (1, "1 year"),
        ("5 years from purchase date", "5 years from purchase date"),
    ]
    for catalog_warranty, expected_warranty in cases:
        product = normalize_product(
            _raw_product(
                99,
                "numeric-warranty",
                "TEST",
                "TEST 185/60/R15 WARRANTY 84H",
                "185",
                "60",
                "R15",
                4500,
                warranty=catalog_warranty,
                is_gulong_guarantee=2,
            ),
            category_name="Mid Range",
            source="test",
            attempt_label="test",
        )

        card = render_product_cards(
            ProductSearchRequest(rim_size="R15").normalized(),
            [product],
        )[0]

        assert product["warranty"] == expected_warranty
        assert card["warranty"] == expected_warranty
        expected_line = (
            f"Warranty: {expected_warranty} + Tire Protection Plan (6 Months)"
        )
        assert expected_line in card["card_text"]

    fallback_product = normalize_product(
        _raw_product(
            100,
            "structured-warranty-fallback",
            "TEST",
            "TEST 185/60/R15 WARRANTY 84H",
            "185",
            "60",
            "R15",
            4500,
            warranty="0",
            warranty_year=6,
        ),
        category_name="Mid Range",
        source="test",
        attempt_label="test",
    )

    assert fallback_product["warranty"] == "6 years"


def test_product_card_keeps_only_trusted_catalog_image_urls():
    trusted_url = (
        "https://gulongph.sgp1.digitaloceanspaces.com/"
        "product_images/New_Main_Product_Image/APOLLO/APOLLO.webp"
    )
    trusted = normalize_product(
        _raw_product(
            981,
            "apollo-with-image",
            "APOLLO",
            "APOLLO 185/60/R15 ALNAC 4G 84H",
            "185",
            "60",
            "R15",
            4500,
            default_image=trusted_url,
        ),
        category_name="Mid Range",
        source="test",
        attempt_label="test",
    )
    untrusted = normalize_product(
        _raw_product(
            982,
            "apollo-bad-image",
            "APOLLO",
            "APOLLO 185/60/R15 AMAZER 84H",
            "185",
            "60",
            "R15",
            4400,
            default_image="https://example.com/not-the-catalog.jpg",
        ),
        category_name="Mid Range",
        source="test",
        attempt_label="test",
    )

    cards = render_product_cards(
        ProductSearchRequest(rim_size="R15").normalized(),
        [trusted, untrusted],
    )

    assert trusted["image_url"] == trusted_url
    assert cards[0]["image_url"] == trusted_url
    assert untrusted["image_url"] is None
    assert cards[1]["image_url"] is None


def test_product_card_includes_installment_text_when_available():
    product = _raw_product(
        102,
        "with-installment",
        "TEST",
        "TEST 185/60/R15 INSTALLMENT 84H",
        "185",
        "60",
        "R15",
        4500,
        installments=[{"bank_name": "BPI", "months_to_pay": 6, "percent_interest": 0}],
    )
    normalized = normalize_product(
        product,
        category_name="Mid Range",
        source="test",
        attempt_label="test",
    )

    card = render_product_cards(ProductSearchRequest(rim_size="R15").normalized(), [normalized])[0]

    assert card["installment_text"] == "BPI 6mo 0% interest"
    assert "💳 BPI 6mo 0% interest" in card["card_text"]


def test_installment_summary_deduplicates_identical_display_facts() -> None:
    summary, minimum_interest = installment_summary(
        [
            {
                "bank_name": "BPI",
                "months_to_pay": 6,
                "percent_interest": 0,
                "source_row_id": 26,
            },
            {
                "bank_name": "BPI",
                "months_to_pay": 6,
                "percent_interest": 0,
                "source_row_id": 41,
            },
            {
                "bank_name": "BDO",
                "months_to_pay": 3,
                "percent_interest": 0,
            },
        ]
    )

    assert summary == "BPI 6mo 0% interest | BDO 3mo 0% interest"
    assert minimum_interest == 0


def test_product_card_omits_dot_when_not_specified():
    product = _raw_product(
        99,
        "no-dot",
        "TEST",
        "TEST 185/60/R15 BASIC 84H",
        "185",
        "60",
        "R15",
        3000,
        dot_sku=None,
    )
    normalized = normalize_product(
        product,
        category_name="Budget",
        source="test",
        attempt_label="test",
    )

    card = render_product_cards(ProductSearchRequest(rim_size="R15").normalized(), [normalized])[0]
    assert "DOT:" not in card["card_text"]
    assert card["dot"] is None


def test_brand_bucket_discovery_returns_deterministic_bucket_cards():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)

    result = runner.discover_brand_buckets({"rim_size": "R15", "top_brands_per_bucket": 2})

    assert result["status"] == "ok"
    assert result["query_basis"]["normalized_filters"]["rim_size"] == "R15"
    assert result["bucket_cards"]
    assert any(card["bucket"] == "budget" and "ATLAS" in card["brands"] for card in result["bucket_cards"])
    assert result["presentation_ref"].startswith("price_categories_")
    assert all(card["choice_ref"].startswith("price_category:") for card in result["bucket_cards"])
    assert all(card["min_price"] <= card["max_price"] for card in result["bucket_cards"])
    assert all(card["brand_count"] > 0 and card["product_count"] > 0 for card in result["bucket_cards"])
    budget_card = next(card for card in result["bucket_cards"] if card["bucket"] == "budget")
    assert "💸 [BUDGET]" in budget_card["card_text"]
    assert "Value-focused brands" in budget_card["card_text"]
    assert "price_range_per_tire" not in budget_card
    assert "PHP 3,040.00-PHP" not in budget_card["card_text"]
    assert result["recommended_response_strategy"].startswith("Ask which bucket")


def test_brand_bucket_discovery_applies_total_budget_filter_and_suggests_product_search():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)

    result = runner.discover_brand_buckets(
        {"rim_size": "R15", "budget_max": 13000, "budget_scope": "total", "quantity": 4}
    )

    assert result["query_basis"]["normalized_filters"]["budget_max"] == 13000.0
    assert result["query_basis"]["normalized_filters"]["budget_scope"] == "total"
    assert result["total_brand_count"] == 1
    assert result["suggested_next_tool"] == "product_search"
    assert [card["brands"] for card in result["bucket_cards"]] == [["ATLAS"]]
    assert all("MICHELIN" not in card["brands"] for card in result["bucket_cards"])


def test_brand_bucket_cards_show_promo_markers_and_legend_without_prices():
    request = ProductSearchRequest(rim_size="R14").normalized()
    product = normalize_product(
        _raw_product(
            97,
            "promo-protect",
            "BFGOODRICH",
            "BFGOODRICH 175/65/R14 ADVANTAGE TOURING 82H",
            "175",
            "65",
            "R14",
            4165,
            tire_type="Mid Range",
            is_gulong_guarantee=1,
            product_discount={
                "name": "BFG Promo",
                "description": "1000 OFF",
                "total_discount": 1000,
                "status_id": 1,
            },
            promo_tag=1,
        ),
        category_name="Mid Range",
        source="test",
        attempt_label="test",
    )
    product["buy3get1_eligible"] = True
    six_month_plan = normalize_product(
        _raw_product(
            96,
            "six-month-plan",
            "CST",
            "CST 175/65/R14 MEDALLION 82H",
            "175",
            "65",
            "R14",
            2800,
            tire_type="Mid Range",
            is_gulong_guarantee=2,
        ),
        category_name="Mid Range",
        source="test",
        attempt_label="test",
    )

    buckets = build_brand_buckets(request, [product, six_month_plan], top_brands_per_bucket=3)
    cards = render_brand_bucket_cards(buckets)
    card = next(card for card in cards if card["bucket"] == "mid_range")

    assert "🛞 [MID RANGE]" in card["card_text"]
    assert "BFGOODRICH (3+1 | PHP 1,000.00 off/tire | TPP 1Y)" in card["card_text"]
    assert "CST (TPP 6 MOS)" in card["card_text"]
    assert "TPP 6M" not in card["card_text"]
    assert "from PHP" not in card["card_text"]
    assert card["marker_legend_keys"] == ["buy3get1", "product_discount", "tpp"]
    assert brand_bucket_legend_text(buckets) == (
        "Legend: 3+1 = Buy 3 Get 1 FREE; PHP off/tire = product discount per tire; "
        "TPP = Tire Protection Plan."
    )


def test_promo_only_cards_do_not_include_non_promo_budget_options():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R16", "promo_only": True, "budget_max": 15000, "budget_scope": "total", "top_k": 4})

    assert result["product_cards"]
    assert all(card["brand"] == "APOLLO" for card in result["product_cards"])
    assert all("Buy 3 Get 1 FREE" in card["card_text"] for card in result["product_cards"])


def test_product_cards_relax_empty_preference_intersection_to_show_alternatives():
    runner = ProductSearchRunner(http_client=PromoUpsellHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R16", "promo_only": True, "tire_categories": ["Budget"], "top_k": 4})

    cards = result["product_cards"]
    assert cards
    assert any(card["category"] == "Budget" for card in cards)
    assert any("Buy 3 Get 1 FREE" in card["card_text"] for card in cards)
    relaxation = result["presentation_strategy"]["relaxation"]
    assert relaxation["applied"] is True
    assert "promo_only" in relaxation["shown_cards_missing_filters"]
    assert "tire_category" in relaxation["shown_cards_missing_filters"]


def test_product_discount_promo_counts_as_active_promo_card():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"brands": ["BFGOODRICH"], "promo_only": True, "top_k": 3})

    card = result["product_cards"][0]
    product = result["best_products"][0]
    assert card["brand"] == "BFGOODRICH"
    assert "PHP 4,165.00/tire | PHP 12,160.20 if for 4 tires" in card["card_text"]
    assert "🎁 BFG Promo: PHP 1,000.00 off/tire | 🎁 Bundle: Save PHP 499.80" in card["card_text"]
    assert "💸 Save PHP 4,499.80!" in card["card_text"]
    assert "| Save PHP 4,499.80\n" not in card["card_text"]
    assert product["price"] == 3165
    assert product["list_price"] == 4165
    assert product["product_discount_amount"] == 1000
    assert product["total_price"] == 12160.2
    assert product["bundle_pricing"]["source"] == "local_policy_product_discount_after_bundle"
    assert product["bundle_pricing"]["tiers"][3]["pre_discount_unit_price"] == 4040.05
    assert product["bundle_pricing"]["tiers"][3]["unit_price"] == 3040.05
    assert "promo_only" in product["match"]["passed_filters"]


def test_bfgoodrich_four_tire_discount_uses_bundle_total_and_manufacturer_warranty():
    product = normalize_product(
        _raw_product(
            7596,
            "bfgoodrich-215-45-r17-advantage-touring-91v",
            "BFGOODRICH",
            "BFGOODRICH 215/45/R17 ADVANTAGE TOURING 91V",
            "215",
            "45",
            "R17",
            6250,
            promo=5250,
            sale_tag=1,
            warranty=None,
            warranty_year=6,
            is_gulong_guarantee=2,
            product_discount={
                "name": "BFG Promo",
                "description": "1000 OFF",
                "total_discount": 1000,
                "status_id": 1,
            },
            tire_type="Mid Range",
        ),
        category_name="Mid Range",
        source="test",
        attempt_label="test",
    )

    card = render_product_cards(ProductSearchRequest(quantity=4), [product])[0]

    assert product["price"] == 5250
    assert product["warranty"] == "6 years"
    assert product["bundle_pricing"]["tiers"][3]["total_price"] == 20250.0
    assert card["deal_price_line"] == "PHP 6,250.00/tire | PHP 20,250.00 if for 4 tires"
    assert "BFG Promo: PHP 1,000.00 off/tire" in card["card_text"]
    assert "Bundle: Save PHP 750.00" in card["card_text"]
    assert "Save PHP 4,750.00!" in card["card_text"]
    assert "Warranty: 6 years + Tire Protection Plan (6 Months)" in card["card_text"]


def test_yokohama_four_tire_discount_uses_bundle_total_and_badge_warranty():
    product = normalize_product(
        _raw_product(
            790,
            "yokohama-215-45-r17-advan-fleva-91w",
            "YOKOHAMA",
            "YOKOHAMA 215/45/R17 ADVAN FLEVA V701 91W",
            "215",
            "45",
            "R17",
            8040,
            promo=7040,
            sale_tag=1,
            warranty=None,
            default_product_banner="https://gulongph.example/Warranty%20Badges%20%5BWebsite%20Icons%5D%205%20Years.png",
            is_gulong_guarantee=1,
            product_discount={
                "name": "YOKOHAMA Promo",
                "description": "1000 OFF",
                "total_discount": 1000,
                "status_id": 1,
            },
            tire_type="Premium",
        ),
        category_name="Premium",
        source="test",
        attempt_label="test",
    )

    card = render_product_cards(ProductSearchRequest(quantity=4), [product])[0]

    assert product["price"] == 7040
    assert product["warranty"] == "5 years"
    assert product["bundle_pricing"]["source"] == "reviewed_yokohama_set_promo_fallback"
    assert product["bundle_pricing"]["set_discount_amount"] == 1200
    assert product["bundle_pricing"]["tiers"][3]["total_price"] == 25995.2
    assert card["deal_price_line"] == "PHP 8,040.00/tire | PHP 25,995.20 if for 4 tires"
    assert "YOKOHAMA Promo: PHP 1,000.00 off/tire" in card["card_text"]
    assert "Bundle: Save PHP 2,164.80" in card["card_text"]
    assert "Save PHP 6,164.80!" in card["card_text"]
    assert "Warranty: 5 years + Tire Protection Plan (1 Year)" in card["card_text"]


def test_yokohama_six_thousand_selected_set_discount_uses_fixed_promo_total():
    product = normalize_product(
        _raw_product(
            910,
            "yokohama-265-65-r17-geolandar-g018",
            "YOKOHAMA",
            "YOKOHAMA 265/65/R17 GEOLANDAR G018 112H",
            "265",
            "65",
            "R17",
            12000,
            promo=11000,
            sale_tag=1,
            product_discount={
                "name": "YOKOHAMA Promo",
                "description": "1000 OFF",
                "total_discount": 1000,
                "status_id": 1,
            },
            banner={
                "label": "PHP 2,000",
                "sub_label": "OFF",
                "description": "PHP 1,000 OFF PER TIRE and additional PHP 2,000 discount for 4-tires",
                "status_id": 1,
            },
            tire_type="Premium",
        ),
        category_name="Premium",
        source="test",
        attempt_label="test",
    )

    card = render_product_cards(ProductSearchRequest(quantity=4), [product])[0]

    assert product["bundle_pricing"]["source"] == "reviewed_yokohama_set_promo_fallback"
    assert product["bundle_pricing"]["set_discount_amount"] == 2000
    assert product["bundle_pricing"]["tiers"][3]["total_price"] == 40560.0
    assert card["deal_price_line"] == "PHP 12,000.00/tire | PHP 40,560.00 if for 4 tires"
    assert "YOKOHAMA Promo: PHP 1,000.00 off/tire" in card["card_text"]
    assert "Bundle: Save PHP 3,440.00" in card["card_text"]
    assert "Save PHP 7,440.00!" in card["card_text"]


def test_yokohama_non_selected_sale_sku_uses_standard_quantity_discount():
    product = normalize_product(
        _raw_product(
            733,
            "yokohama-215-55-r16-bluearth-ace-97w",
            "YOKOHAMA",
            "YOKOHAMA 215/55/R16 BLUEARTH GT AE51 97W",
            "215",
            "55",
            "R16",
            8425,
            promo=7425,
            sale_tag=1,
            product_discount={
                "name": "YOKOHAMA Promo",
                "description": "1000 OFF",
                "total_discount": 1000,
                "status_id": 1,
            },
            banner={
                "label": "PHP 1,000",
                "sub_label": "OFF",
                "description": "PHP 1,000 OFF PER TIRE",
                "status_id": 1,
            },
            tire_type="Premium",
        ),
        category_name="Premium",
        source="test",
        attempt_label="test",
    )

    card = render_product_cards(ProductSearchRequest(quantity=4), [product])[0]

    assert product["bundle_pricing"]["source"] == "local_policy_product_discount_after_bundle"
    assert product["bundle_pricing"]["tiers"][3]["total_price"] == 28689.0
    assert card["deal_price_line"] == "PHP 8,425.00/tire | PHP 28,689.00 if for 4 tires"
    assert "YOKOHAMA Promo: PHP 1,000.00 off/tire" in card["card_text"]
    assert "Bundle: Save PHP 1,011.00" in card["card_text"]
    assert "Save PHP 5,011.00!" in card["card_text"]


def test_yokohama_banner_additional_discount_is_primary_signal_before_sku_table():
    product = normalize_product(
        _raw_product(
            991,
            "yokohama-banner-only-test",
            "YOKOHAMA",
            "YOKOHAMA 215/55/R16 TEST PATTERN 97W",
            "215",
            "55",
            "R16",
            9000,
            promo=8000,
            sale_tag=1,
            product_discount={
                "name": "YOKOHAMA Promo",
                "description": "1000 OFF",
                "total_discount": 1000,
                "status_id": 1,
            },
            banner={
                "label": "PHP 1,200",
                "sub_label": "OFF",
                "description": "PHP 1,000 OFF PER TIRE and additional PHP 1,200 discount for 4-tires",
                "status_id": 1,
            },
            tire_type="Premium",
        ),
        category_name="Premium",
        source="test",
        attempt_label="test",
    )

    card = render_product_cards(ProductSearchRequest(quantity=4), [product])[0]

    assert product["bundle_pricing"]["source"] == "reviewed_yokohama_set_promo_fallback"
    assert product["bundle_pricing"]["set_discount_amount"] == 1200
    assert product["bundle_pricing"]["tiers"][3]["total_price"] == 29720.0
    assert "Bundle: Save PHP 2,280.00" in card["card_text"]
    assert "Save PHP 6,280.00!" in card["card_text"]


def test_api_product_promo_drives_quantity_tiers_for_any_brand():
    product = normalize_product(
        _raw_product(
            417,
            "yokohama-175-65-r14-bluearth-es32-82t",
            "YOKOHAMA",
            "YOKOHAMA 175/65/R14 BLUEARTH ES32 82T",
            "175",
            "65",
            "R14",
            5480,
            promo=4480,
            sale_tag=1,
            product_discount={
                "name": "Yokohama Promo",
                "total_discount": 1000,
                "status_id": 1,
            },
            product_promo={
                "id": 35,
                "discount_amount": 1200,
                "required_quantity": 4,
                "status_id": 1,
            },
        ),
        category_name="Premium",
        source="test",
        attempt_label="test",
    )

    tiers = product["bundle_pricing"]["tiers"]
    assert product["bundle_pricing"]["source"] == "api_product_promo"
    assert product["bundle_pricing"]["product_promo_ref"] == 35
    assert [tier["total_price"] for tier in tiers] == [4480.0, 8850.4, 13111.2, 16062.4]
    assert tiers[3]["total_before_quantity_promo"] == 17262.4
    assert tiers[3]["quantity_promo_discount_amount"] == 1200.0
    card = render_product_cards(ProductSearchRequest(quantity=4), [product])[0]
    assert card["deal_price_line"] == (
        "PHP 4,315.60/tire x 4 | PHP 16,062.40 after PHP 1,200.00 promo"
    )
    assert card["pricing_facts"]["payable_total"] == 16062.4
    assert card["pricing_facts"]["total_before_quantity_promo"] == 17262.4
    assert card["pricing_facts"]["quantity_tier_unit_price"] == 4315.6
    assert card["pricing_facts"]["quantity_promo_discount_amount"] == 1200.0
    assert card["pricing_facts"]["product_promo_ref"] == 35
    assert "total_savings" not in card["pricing_facts"]
    assert card["pricing_facts"]["included_promos"] == [
        "Yokohama Promo: PHP 1,000.00 off/tire",
        "Quantity promo: PHP 1,200.00 off",
    ]
    assert card["promo_savings_line"] == (
        "Yokohama Promo: PHP 1,000.00 off/tire | Quantity promo: PHP 1,200.00 off"
    )

    other_brand = normalize_product(
        _raw_product(
            999,
            "other-api-quantity-promo",
            "OTHER",
            "OTHER 175/65/R14 TEST 82T",
            "175",
            "65",
            "R14",
            5000,
            product_promo={
                "id": 99,
                "discount_amount": 750,
                "required_quantity": 3,
                "status_id": 1,
            },
        ),
        category_name="Economy",
        source="test",
        attempt_label="test",
    )
    assert other_brand["bundle_pricing"]["source"] == "api_product_promo"
    assert [tier["total_price"] for tier in other_brand["bundle_pricing"]["tiers"]] == [
        5000.0,
        9900.0,
        13950.0,
        18650.0,
    ]


def test_inactive_or_malformed_api_product_promo_is_ignored():
    for product_promo in (
        {"id": 1, "discount_amount": 1200, "required_quantity": 4, "status_id": 0},
        {"id": 2, "discount_amount": 1200, "required_quantity": 0, "status_id": 1},
        {"id": 3, "discount_amount": 0, "required_quantity": 4, "status_id": 1},
    ):
        product = normalize_product(
            _raw_product(
                999,
                "other-invalid-promo",
                "OTHER",
                "OTHER 175/65/R14 TEST 82T",
                "175",
                "65",
                "R14",
                5000,
                product_promo=product_promo,
            ),
            category_name="Economy",
            source="test",
            attempt_label="test",
        )
        assert product["bundle_pricing"]["source"] == "local_policy"


def test_product_card_quantity_pricing_shows_base_unit_and_quantity_total():
    product = normalize_product(
        _raw_product(
            120,
            "fronway-bundle",
            "FRONWAY",
            "FRONWAY 185/70/R14 ECOGREEN ONE 88H",
            "185",
            "70",
            "R14",
            2430,
            origin_country="China",
            warranty="5 years from purchase date",
            is_gulong_guarantee=1,
        ),
        category_name="Budget",
        source="test",
        attempt_label="test",
    )

    one = render_product_cards(ProductSearchRequest(quantity=1), [product])[0]
    two = render_product_cards(ProductSearchRequest(quantity=2), [product])[0]
    three = render_product_cards(ProductSearchRequest(quantity=3), [product])[0]
    four = render_product_cards(ProductSearchRequest(quantity=4), [product])[0]

    assert "💰 PHP 2,430.00/tire" in one["card_text"]
    assert "for 1 tire" not in one["card_text"]
    assert "🎁" not in one["card_text"]
    assert one["promo_savings_line"] is None

    assert "💰 PHP 2,430.00/tire | PHP 4,811.40 for 2 tires" in two["card_text"]
    assert "🎁 Bundle: Save PHP 48.60" in two["card_text"]

    assert "💰 PHP 2,430.00/tire | PHP 7,144.20 for 3 tires" in three["card_text"]
    assert "🎁 Bundle: Save PHP 145.80" in three["card_text"]

    assert "💰 PHP 2,430.00/tire | PHP 9,428.40 if for 4 tires" in four["card_text"]
    assert "🎁 Bundle: Save PHP 291.60" in four["card_text"]


def test_exact_size_request_does_not_present_same_rim_promo_cards():
    runner = ProductSearchRunner(http_client=ExactSizeWithSameRimPromoHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "section_width": "205",
            "aspect_ratio": "45",
            "rim_size": "R17",
            "quantity": 4,
            "budget_max": 18000,
            "budget_scope": "total",
            "promo_only": True,
            "top_k": 6,
        }
    )

    cards = result["product_cards"]
    assert cards
    assert all("205/45" in card["sku_model"] for card in cards)
    assert all("215/45" not in card["sku_model"] for card in cards)
    assert all("205/50" not in card["sku_model"] for card in cards)
    assert all("Buy 3 Get 1 FREE" in card["card_text"] for card in cards)


def test_exact_size_promo_request_prefers_strict_promo_cards_when_available():
    runner = ProductSearchRunner(http_client=ExactSizeMixedPromoHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "section_width": "215",
            "aspect_ratio": "50",
            "rim_size": "R18",
            "quantity": 4,
            "promo_only": True,
            "promo_types": ["buy3get1"],
            "top_k": 6,
        }
    )

    cards = result["product_cards"]
    assert [card["brand"] for card in cards] == ["MICHELIN"]
    assert all("Buy 3 Get 1 FREE" in card["card_text"] for card in cards)
    assert "relaxation" not in result["presentation_strategy"]


def test_buy3get1_promo_type_excludes_product_discount_promo():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"brands": ["BFGOODRICH"], "promo_only": True, "promo_types": ["buy3get1"], "top_k": 3})

    assert result["product_cards"]
    assert result["presentation_strategy"]["relaxation"]["applied"] is True
    assert result["best_products"][0]["brand"] == "BFGOODRICH"
    assert "promo_only" in result["best_products"][0]["match"]["missed_filters"]


def test_named_buy3get1_promo_type_implies_promo_only_for_four_tires():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R16", "quantity": 4, "promo_types": ["buy3get1"], "top_k": 3})

    filters = result["query_basis"]["normalized_filters"]
    assert filters["promo_only"] is True
    assert filters["promo_types"] == ["buy3get1"]
    assert result["best_products"][0]["brand"] == "APOLLO"
    assert "promo_only" in result["best_products"][0]["match"]["passed_filters"]


def test_named_buy3get1_without_order_quantity_uses_four_tire_search_scope():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R16", "promo_types": ["buy3get1"], "top_k": 3})

    filters = result["query_basis"]["normalized_filters"]
    assert filters["quantity"] == 4
    assert filters["promo_only"] is True
    assert filters["promo_types"] == ["buy3get1"]
    assert all("Buy 3 Get 1 FREE" in card["card_text"] for card in result["product_cards"])


def test_buy3get1_quantity_conflict_exposes_split_search_guidance():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R16", "quantity": 2, "promo_types": ["buy3get1"], "top_k": 3})

    context = result["quantity_promo_context"]
    assert context["status"] == "quantity_promo_conflict"
    assert context["current_quantity"] == 2
    assert context["promo_requires_quantity"] == 4
    labels = [item["label"] for item in context["suggested_followup_searches"]]
    assert labels == ["current_quantity_regular_options", "four_tire_buy3get1_options"]
    assert context["suggested_followup_searches"][0]["args"]["quantity"] == 2
    assert context["suggested_followup_searches"][1]["args"]["quantity"] == 4
    assert context["suggested_followup_searches"][1]["args"]["promo_only"] is True
    assert context["suggested_followup_searches"][1]["args"]["promo_types"] == ["buy3get1"]
    assert result["presentation_strategy"]["quantity_promo_context"]["status"] == "quantity_promo_conflict"


def test_buy3get1_label_is_not_rendered_as_applied_to_two_tires():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R16", "quantity": 2, "promo_types": ["buy3get1"], "top_k": 3})

    apollo = next(card for card in result["product_cards"] if card["brand"] == "APOLLO")
    assert "for 2 tires" in apollo["card_text"]
    assert "Buy 3 Get 1 FREE" not in apollo["card_text"]


def test_product_card_suppresses_numeric_only_promo_text_and_uses_singular_tire():
    request = ProductSearchRequest(section_width="195", aspect_ratio="45", rim_size="R17", quantity=1)
    cards = render_product_cards(
        request,
        [
            {
                "brand": "NANKANG",
                "model": "NANKANG 195/45/R17 AS-1 85H",
                "size": "195/45R17",
                "section_width": "195",
                "aspect_ratio": "45",
                "rim_size": "R17",
                "price": 4355,
                "category": "Economy",
                "promo_text": "4355",
                "url": "https://gulong.ph/product/nankang-195-45-r17-as-1-85h",
            }
        ],
    )

    card = cards[0]
    assert "PHP 4,355.00/tire" in card["card_text"]
    assert "for 1 tire" not in card["card_text"]
    assert "for 1 tires" not in card["card_text"]
    assert card["promo_savings_line"] is None
    assert card["tire_size"] == "195/45R17"


def test_budget_cards_fill_to_target_with_promo_upsell():
    runner = ProductSearchRunner(http_client=PromoUpsellHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R16", "promo_only": True, "budget_max": 15000, "budget_scope": "total", "top_k": 4})

    cards = result["product_cards"]
    brands = [card["brand"] for card in cards]
    assert brands == ["VREDESTEIN", "APOLLO", "MICHELIN"]
    assert len(cards) == 3
    assert all("Buy 3 Get 1 FREE" in card["card_text"] for card in cards)
    assert "OTHER" not in brands
    assert cards[-1]["why_shown"] == "nearest option to requested budget"


def test_runner_recovers_from_zero_exact_to_rim_only_partial():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "section_width": "225",
            "aspect_ratio": "45",
            "rim_size": "R15",
            "brands": ["MissingBrand"],
            "top_k": 3,
        }
    )

    assert result["status"] == "exact_unavailable"
    assert result["query_basis"]["exact_base_query_verified"] is True
    assert result["product_cards"] == []
    assert result["presented_products"] == []
    assert result["result_pool_summary"]["partial"] > 0
    assert any(attempt["product_count"] == 0 for attempt in result["attempted_queries"])
    assert "rim_only" in {attempt["label"] for attempt in result["attempted_queries"]}


def test_multi_brand_uses_combined_and_split_attempts_with_dedupe():
    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=8)
    result = runner.run({"brands": ["Michelin", "Yokohama"], "top_k": 5})

    brand_params = [call["params"].get("b") for call in client.post_calls if call["params"].get("b")]
    assert "MICHELIN--YOKOHAMA" in brand_params
    assert "MICHELIN" in brand_params
    assert "YOKOHAMA" in brand_params
    slugs = [product["slug"] for product in result["best_products"]]
    assert len(slugs) == len(set(slugs))


def test_multi_required_brands_populates_requested_brand_status():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run({"rim_size": "R15", "required_brands": ["Michelin", "Yokohama"], "top_k": 5})

    filters = result["query_basis"]["normalized_filters"]
    assert set(filters["brands"]) == {"MICHELIN", "YOKOHAMA"}
    assert filters["preferred_brands"] == []
    status = result["requested_brand_status"]
    assert set(status["requested"]) == {"MICHELIN", "YOKOHAMA"}
    assert {"MICHELIN", "YOKOHAMA"}.issubset(set(status["matched"]))
    assert result["product_cards"]


def test_requested_brand_other_size_does_not_block_exact_size_alternatives():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "section_width": "265",
            "aspect_ratio": "35",
            "rim_size": "ZR21",
            "required_brands": ["Yokohama"],
            "top_k": 3,
        }
    )

    status = result["requested_brand_status"]
    assert status["requested"] == ["YOKOHAMA"]
    assert status["matched"] == []
    assert status["missing"] == ["YOKOHAMA"]
    assert status["presented"] == []
    assert status["available_outside_requested_filters"] == ["YOKOHAMA"]
    assert "no requested-brand product found for the strongest size/rim filter" in result["no_match_reasons"]
    assert result["product_cards"]
    assert {card["tire_size"] for card in result["product_cards"]} == {"265/35ZR21"}
    assert all("brand" in card["missing_requested_filters"] for card in result["product_cards"])
    assert "YOKOHAMA" not in {card["brand"] for card in result["product_cards"]}


def test_model_only_uses_catalog_fallback():
    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=4)
    result = runner.run({"model_or_pattern": "Geolandar", "top_k": 3})

    assert "/product_list" in client.get_calls
    assert result["best_products"]
    assert result["best_products"][0]["slug"] == "yoko-geolandar"
    assert result["requested_model_pattern_status"]["used"] is True


def test_model_pattern_fuzzy_typos_match_catalog_fallback():
    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=4)
    result = runner.run({"model_or_pattern": "giolander", "top_k": 3})

    assert "/product_list" in client.get_calls
    assert result["best_products"][0]["slug"] == "yoko-geolandar"
    assert "model_or_pattern" in result["best_products"][0]["match"]["passed_filters"]


def test_model_match_score_handles_common_typos_without_lowering_threshold():
    cases = [
        ("giolander", "YOKOHAMA 265/50/R20 GEOLANDAR A/T G015 111W"),
        ("pilot spor", "MICHELIN 265/35/ZR21 PILOT SPORT EV 101Y"),
        ("blue eart", "YOKOHAMA 185/60/R15 BLUEARTH ES32 84H"),
    ]
    for query, text in cases:
        assert model_match_score(query, text) >= model_match_threshold(query)


def test_model_or_pattern_search_uses_slug_for_sku_like_codes():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"model_or_pattern": "TRN123", "top_k": 3})

    assert result["best_products"][0]["slug"] == "trn123-touring"
    assert "sku" not in result["best_products"][0]


def test_model_only_recovers_to_broad_shop_when_catalog_misses():
    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=4)
    result = runner.run({"model_or_pattern": "Pilot Sport", "top_k": 3})

    assert result["best_products"][0]["slug"] == "shop-pilot-sport"
    assert [attempt["label"] for attempt in result["attempted_queries"]] == [
        "catalog_fallback",
        "broad_discovery",
    ]


def test_brand_model_rim_cards_anchor_to_exact_full_size():
    runner = ProductSearchRunner(http_client=MichelinPilotRimHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "required_brands": ["Michelin"],
            "model_or_pattern": "Pilot Sport",
            "rim_size": "15",
            "soft_preferences": ["compare alternatives"],
        }
    )

    cards = result["product_cards"]
    assert [card["slug"] for card in cards] == [
        "michelin-pilot-r15",
        "bfg-same-size-r15",
        "yokohama-same-size-r15",
    ]
    assert len(cards) == 3
    assert all("195/50/R15" in card["sku_model"] for card in cards)
    assert "deestone-other-r15" not in {card["slug"] for card in cards}
    assert cards[0]["why_shown"] == "matches requested brand/model/rim"
    assert cards[1]["why_shown"] == "same tire size alternative"
    assert result["presentation_strategy"]["alternative_scope"] == "same_full_size_alternatives"


def test_brand_model_rim_cards_show_anchor_only_without_same_size_alternatives():
    runner = ProductSearchRunner(
        http_client=MichelinPilotRimHTTPClient(include_same_size_alternatives=False),
        max_api_calls=8,
    )
    result = runner.run({"required_brands": ["Michelin"], "model_or_pattern": "Pilot Sport", "rim_size": "15"})

    assert [card["slug"] for card in result["product_cards"]] == ["michelin-pilot-r15"]
    assert result["presentation_strategy"]["presentation_scopes"] == ["requested_brand_model_rim_anchor"]


def test_brand_model_rim_cards_allow_same_rim_alternatives_when_requested():
    runner = ProductSearchRunner(
        http_client=MichelinPilotRimHTTPClient(include_same_size_alternatives=False),
        max_api_calls=8,
    )
    result = runner.run(
        {
            "required_brands": ["Michelin"],
            "model_or_pattern": "Pilot Sport",
            "rim_size": "15",
            "soft_preferences": ["compare alternatives"],
        }
    )

    cards = result["product_cards"]
    assert [card["slug"] for card in cards] == ["michelin-pilot-r15", "deestone-other-r15"]
    assert cards[1]["why_shown"] == "same rim alternative"
    assert result["presentation_strategy"]["alternative_scope"] == "same_rim_alternatives"


def test_catalog_fallback_uses_warm_product_list_cache():
    ProductSearchRunner.clear_catalog_cache()
    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=4, use_catalog_cache=True)

    first = runner.run({"model_or_pattern": "Geolandar", "top_k": 3})
    second = runner.run({"model_or_pattern": "Primacy", "top_k": 3})

    assert first["best_products"][0]["slug"] == "yoko-geolandar"
    assert second["best_products"][0]["slug"] == "michelin-primacy"
    assert client.get_calls.count("/product_list") == 1
    second_catalog = next(attempt for attempt in second["attempted_queries"] if attempt["label"] == "catalog_fallback")
    assert second_catalog["cache_status"] == "hit"


def test_catalog_cache_does_not_leak_between_unconfigured_http_clients():
    ProductSearchRunner.clear_catalog_cache()
    first_client = FakeHTTPClient()
    first_runner = ProductSearchRunner(http_client=first_client, max_api_calls=4, use_catalog_cache=True)
    second_client = FakeHTTPClient()
    second_runner = ProductSearchRunner(http_client=second_client, max_api_calls=4, use_catalog_cache=True)

    first_runner.run({"model_or_pattern": "Geolandar", "top_k": 3})
    second_runner.run({"model_or_pattern": "Geolandar", "top_k": 3})

    assert first_client.get_calls.count("/product_list") == 1
    assert second_client.get_calls.count("/product_list") == 1


def test_warm_catalog_cache_populates_product_list_cache():
    ProductSearchRunner.clear_catalog_cache()
    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=4, use_catalog_cache=True)

    warm = runner.warm_catalog_cache()
    result = runner.run({"model_or_pattern": "Geolandar", "top_k": 3})

    assert warm["status"] == "ok"
    assert warm["product_count"] == 8
    assert client.get_calls.count("/product_list") == 1
    catalog = next(attempt for attempt in result["attempted_queries"] if attempt["label"] == "catalog_fallback")
    assert catalog["cache_status"] == "hit"


def test_request_uses_brands_list_contract():
    req = ProductSearchRequest.from_mapping({"brands": "Yokohama/Michelin"})
    assert req.normalized().brands == ["YOKOHAMA", "MICHELIN"]


def test_brand_normalization_handles_common_customer_typos():
    req = ProductSearchRequest.from_mapping(
        {
            "brands": [
                "micheline",
                "yokohana",
                "bfgudruch",
                "arrivo",
                "weslake",
                "bridgeston",
            ]
        }
    ).normalized()

    assert req.brands == [
        "MICHELIN",
        "YOKOHAMA",
        "BFGOODRICH",
        "ARIVO",
        "WESTLAKE",
        "BRIDGESTONE",
    ]
    assert {item["input"] for item in req.brand_corrections} == {
        "micheline",
        "yokohana",
        "bfgudruch",
        "arrivo",
        "weslake",
        "bridgeston",
    }


def test_brand_typo_canonicalizes_before_shop_attempt():
    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=4)

    result = runner.run({"rim_size": "R15", "brands": ["micheline"], "top_k": 3})

    brand_params = [call["params"].get("b") for call in client.post_calls if call["params"].get("b")]
    assert "MICHELIN" in brand_params
    assert "MICHELINE" not in brand_params
    assert result["query_basis"]["normalized_filters"]["brands"] == ["MICHELIN"]
    assert result["query_basis"]["normalized_filters"]["brand_corrections"][0]["canonical"] == "MICHELIN"
    assert result["best_products"][0]["brand"] == "MICHELIN"


def test_product_search_corrects_one_off_metric_section_width_typo():
    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=4)

    result = runner.run({"section_width": "164", "aspect_ratio": "60", "rim_size": "14", "top_k": 3})

    filters = result["query_basis"]["normalized_filters"]
    assert filters["section_width"] == "165"
    assert filters["aspect_ratio"] == "60"
    assert filters["rim_size"] == "R14"
    assert filters["size_corrections"][0]["input"] == "164/60R14"
    assert filters["size_corrections"][0]["canonical"] == "165/60R14"
    attempted_sections = [call["params"].get("section_width") for call in client.post_calls if call["params"].get("section_width")]
    assert "165" in attempted_sections
    assert "164" not in attempted_sections


def test_ply_rating_prefers_commercial_c_rim_without_dropping_valid_profile():
    request = ProductSearchRequest.from_mapping(
        {"section_width": "195", "aspect_ratio": "70", "rim_size": "14", "ply_rating": "8 ply"}
    ).normalized()

    assert request.rim_size == "R14C"
    assert request.aspect_ratio == "70"
    assert request.ply_rating == 8


def test_metric_section_width_correction_does_not_touch_flotation_sizes():
    assert normalize_metric_section_width_with_corrections(
        "33",
        aspect_ratio="10.5",
        rim_size="15",
    ) == ("33", [])
    assert normalize_metric_section_width_with_corrections(
        "10.5",
        aspect_ratio=None,
        rim_size="15",
    ) == ("10.50", [])


class FakeCanonicalProvider:
    def __init__(self):
        self.brand_calls = 0

    def brands(self):
        self.brand_calls += 1
        return ["NEWBRAND"]


def test_product_search_uses_provider_only_for_unknown_catalog_brand():
    client = FakeHTTPClient()
    provider = FakeCanonicalProvider()
    runner = ProductSearchRunner(
        http_client=client,
        canonical_values_provider=provider,
        max_api_calls=4,
    )

    result = runner.run({"rim_size": "R15", "brands": ["newbrnd"], "top_k": 3})

    brand_params = [call["params"].get("b") for call in client.post_calls if call["params"].get("b")]
    assert provider.brand_calls == 1
    assert "NEWBRAND" in brand_params
    assert result["query_basis"]["normalized_filters"]["brands"] == ["NEWBRAND"]
    assert result["best_products"][0]["brand"] == "NEWBRAND"


def test_promo_only_uses_promo_brand_authority_over_promo_tag():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R16", "promo_only": True, "top_k": 3})

    assert result["best_products"][0]["brand"] == "APOLLO"
    assert result["best_products"][0]["buy3get1_eligible"] is True
    assert "promo_only" in result["best_products"][0]["match"]["passed_filters"]
    other = next(product for product in result["best_products"] if product["brand"] == "OTHER")
    assert other["buy3get1_eligible"] is False
    assert other["bundle_pricing"]["source"] == "local_policy"
    assert "promo_only" in other["match"]["missed_filters"]


def test_promo_only_renders_exact_size_fallback_with_explicit_promo_mismatch():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)

    result = runner.run(
        {
            "section_width": "185",
            "aspect_ratio": "60",
            "rim_size": "R15",
            "brands": ["YOKOHAMA"],
            "promo_only": True,
            "promo_types": ["buy3get1"],
            "quantity": 4,
        }
    )

    assert result["status"] == "partial_match"
    assert len(result["product_cards"]) == 1
    assert result["product_cards"][0]["brand"] == "YOKOHAMA"
    assert result["product_cards"][0]["missing_requested_filters"] == ["promo_only"]
    assert "requested promo" in result["product_cards"][0]["card_text"]
    assert "Buy 3 Get 1 FREE" not in result["product_cards"][0]["card_text"]
    assert result["best_products"][0]["brand"] == "YOKOHAMA"
    assert "promo_only" in result["best_products"][0]["match"]["missed_filters"]
    assert result["promo_evidence"]["requested_brands_not_eligible"] == ["YOKOHAMA"]


def test_promo_brand_without_product_promo_tag_uses_buy3get1_total():
    runner = ProductSearchRunner(http_client=PromoBrandAuthorityHTTPClient(), max_api_calls=4)
    result = runner.run(
        {
            "section_width": "225",
            "aspect_ratio": "60",
            "rim_size": "R18",
            "brands": ["MICHELIN"],
            "quantity": 4,
            "top_k": 3,
        }
    )

    product = result["best_products"][0]
    assert product["brand"] == "MICHELIN"
    assert product["price"] == 14050
    assert not product.get("promo_tag")
    assert product["buy3get1_eligible"] is True
    assert product["total_price"] == 42150
    assert product["pricing_basis"] == "buy3get1"
    assert product["bundle_pricing"]["source"] == "disabled_for_buy3get1"
    assert product["bundle_pricing"]["tiers"] == []
    assert product["promo_text"] == "PHP 42,150.00 if for 4 tires"

    card = result["product_cards"][0]
    assert card["brand"] == "MICHELIN"
    assert "PHP 14,050.00/tire | PHP 42,150.00 if for 4 tires" in card["card_text"]
    assert "Buy 3 Get 1 FREE" in card["card_text"]
    assert "Bundle: Save" not in card["card_text"]


def test_buy3get1_required_brand_filter_uses_promo_brands_not_sku_tag():
    runner = ProductSearchRunner(http_client=PromoBrandAuthorityHTTPClient(), max_api_calls=4)
    result = runner.run(
        {
            "section_width": "215",
            "aspect_ratio": "55",
            "rim_size": "R16",
            "required_brands": ["Michelin"],
            "promo_types": ["buy3get1"],
            "quantity": 4,
            "top_k": 3,
        }
    )

    product = result["best_products"][0]
    assert product["brand"] == "MICHELIN"
    assert product["slug"] == "michelin-215-55-r16-primacy-5-97w"
    assert product["price"] == 10990
    assert product["list_price"] == 11990
    assert product.get("product_discount_label") is None
    assert product.get("product_discount_text") is None
    assert product.get("product_discount_amount") is None
    assert product.get("promo_tag") is None
    assert product["buy3get1_eligible"] is True
    assert product["total_price"] == 32970
    assert product["pricing_basis"] == "buy3get1"
    assert "promo_only" in product["match"]["passed_filters"]
    assert product["bundle_pricing"]["source"] == "disabled_for_buy3get1"

    card = result["product_cards"][0]
    card_text = card["card_text"]
    assert "PHP 10,990.00/tire | PHP 32,970.00 if for 4 tires" in card_text
    assert "Buy 3 Get 1 FREE" in card_text
    assert "Save PHP 10,990.00" in card_text
    assert "PHP 1,000.00 off/tire already reflected in unit price" in card_text
    assert "Bundle: Save" not in card_text
    pricing_facts = card["pricing_facts"]
    assert pricing_facts["unit_price"] == 10990
    assert pricing_facts["payable_total"] == 32970
    assert pricing_facts["sale_discount_per_tire"] == 1000
    assert pricing_facts["sale_discount_per_tire_text"] == "PHP 1,000.00/tire"
    assert pricing_facts["unit_price_already_includes_sale_discount"] is True
    assert pricing_facts["included_promos"] == [
        "PHP 1,000.00 off/tire already reflected in unit price",
        "Buy 3 Get 1 FREE",
    ]


def test_sale_price_discount_satisfies_exact_michelin_product_discount_search():
    runner = ProductSearchRunner(http_client=PromoBrandAuthorityHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "section_width": "175",
            "aspect_ratio": "65",
            "rim_size": "R14",
            "required_brands": ["Michelin"],
            "promo_only": True,
            "promo_types": ["product_discount"],
            "quantity": 4,
            "top_k": 3,
        }
    )

    product = result["best_products"][0]
    assert result["status"] == "ok"
    assert product["slug"] == "michelin-175-65-r14-energy-xm2"
    assert "promo_only" in product["match"]["passed_filters"]
    assert product["match"]["tier"] == "exact"
    card = result["product_cards"][0]
    assert card["brand"] == "MICHELIN"
    assert "PHP 1,000.00 off/tire already reflected in unit price" in card["promo_savings_line"]
    assert "Buy 3 Get 1 FREE" in card["promo_savings_line"]
    assert {item["brand"] for item in result["product_cards"]} == {"MICHELIN"}
    assert "presentation_catalog_alternatives" not in {
        attempt["label"] for attempt in result["attempted_queries"]
    }


def test_promo_tag_buy3get1_uses_website_card_price_not_hidden_promo_value():
    runner = ProductSearchRunner(http_client=PromoBrandAuthorityHTTPClient(), max_api_calls=4)

    cases = [
        {
            "brand": "APOLLO",
            "payload": {
                "section_width": "215",
                "aspect_ratio": "55",
                "rim_size": "R16",
                "required_brands": ["Apollo"],
                "promo_types": ["buy3get1"],
                "quantity": 4,
                "top_k": 3,
            },
            "slug": "apollo-215-55-r16-alnac-4g",
            "price": 7105,
            "hidden_promo": 5330,
            "total": 21315,
        },
        {
            "brand": "VREDESTEIN",
            "payload": {
                "section_width": "175",
                "aspect_ratio": "65",
                "rim_size": "R14",
                "required_brands": ["Vredestein"],
                "promo_types": ["buy3get1"],
                "quantity": 4,
                "top_k": 3,
            },
            "slug": "vredestein-175-65-r14-t-trac-2-86t+1",
            "price": 4280,
            "hidden_promo": 3210,
            "total": 12840,
        },
    ]

    for case in cases:
        result = runner.run(case["payload"])
        product = result["best_products"][0]
        card = result["product_cards"][0]
        card_text = card["card_text"]
        pricing_facts = card["pricing_facts"]

        assert product["brand"] == case["brand"]
        assert product["slug"] == case["slug"]
        assert product["price"] == case["price"]
        assert product.get("list_price") is None
        assert product.get("product_discount_amount") is None
        assert product["buy3get1_eligible"] is True
        assert product["total_price"] == case["total"]
        assert product["pricing_basis"] == "buy3get1"
        assert f"PHP {case['price']:,.2f}/tire | PHP {case['total']:,.2f} if for 4 tires" in card_text
        assert "Buy 3 Get 1 FREE" in card_text
        assert f"PHP {case['hidden_promo']:,.2f}/tire" not in card_text
        assert "Bundle: Save" not in card_text
        assert pricing_facts["unit_price"] == case["price"]
        assert pricing_facts["payable_total"] == case["total"]
        assert "sale_discount_per_tire" not in pricing_facts
        assert "unit_price_already_includes_sale_discount" not in pricing_facts


def test_total_budget_includes_buy3get1_promo_price():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run(
        {
            "rim_size": "R16",
            "brands": ["APOLLO"],
            "promo_only": True,
            "budget_max": 15000,
            "budget_scope": "total",
            "quantity": 4,
            "top_k": 3,
        }
    )

    top = result["best_products"][0]
    assert top["brand"] == "APOLLO"
    assert top["total_price"] == 15000
    assert "budget_max" in top["match"]["passed_filters"]
    assert "promo_only" in top["match"]["passed_filters"]


def test_total_budget_uses_regular_bundle_tier_when_no_buy3get1():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run(
        {
            "rim_size": "R18",
            "brands": ["NOGUARANTEE"],
            "budget_max": 23500,
            "budget_scope": "total",
            "quantity": 4,
            "top_k": 3,
        }
    )

    top = result["best_products"][0]
    assert top["brand"] == "NOGUARANTEE"
    assert top["total_price"] == 23280
    assert top["pricing_basis"] == "bundle_tier"
    assert "budget_max" in top["match"]["passed_filters"]


def test_bundle_pricing_can_be_disabled_without_breaking_budget_logic():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4, enable_bundle_pricing=False)
    result = runner.run(
        {
            "rim_size": "R18",
            "brands": ["NOGUARANTEE"],
            "budget_max": 23500,
            "budget_scope": "total",
            "quantity": 4,
            "top_k": 3,
        }
    )

    top = result["best_products"][0]
    assert top["brand"] == "NOGUARANTEE"
    assert top["total_price"] == 24000
    assert top["pricing_basis"] == "unit_price"
    assert top["bundle_pricing"]["source"] == "disabled_by_config"
    assert "budget_max" in top["match"]["missed_filters"]


def test_commercial_rim_suffix_is_preserved_and_not_passenger_equivalent():
    assert normalize_rim_size("15C") == "R15C"
    assert normalize_rim_size("R15C") == "R15C"
    assert rim_matches("R15C", "R15C") is True
    assert rim_matches("R15C", "R15") is False
    assert rim_matches("R15", "R15C") is False


def test_commercial_width_rim_search_uses_c_suffix():
    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=4)
    result = runner.run({"section_width": "195", "rim_size": "15C", "top_k": 3})

    assert result["status"] == "ok"
    assert result["best_products"][0]["rim_size"] == "R15C"
    assert "rim_size" in result["best_products"][0]["match"]["passed_filters"]
    assert any(call["params"].get("rim_size") == "R15C" for call in client.post_calls)


def test_commercial_no_aspect_request_includes_implicit_and_80_profile():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"section_width": "195", "rim_size": "14C", "top_k": 3})

    slugs = [product["slug"] for product in result["best_products"]]
    assert "commercial-r14c-implicit" in slugs
    assert "commercial-r14c-80" in slugs
    assert "commercial-r14c-70" in slugs
    profile_matches = {
        product["slug"]: product["match"]["soft_matches"]
        for product in result["best_products"]
    }
    assert "commercial_implicit_profile" in profile_matches["commercial-r14c-implicit"]
    assert "commercial_70_plus_profile" in profile_matches["commercial-r14c-80"]
    assert "commercial_70_plus_profile" in profile_matches["commercial-r14c-70"]


def test_commercial_bad_aspect_marker_is_dropped_and_keeps_c_rim_exact():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"section_width": "195", "aspect_ratio": "R", "rim_size": "14C", "brands": ["Commercial"], "top_k": 3})

    filters = result["query_basis"]["normalized_filters"]
    assert filters["aspect_ratio"] is None
    assert filters["rim_size"] == "R14C"
    assert result["status"] == "ok"
    assert result["result_level"] == "exact"
    assert result["product_cards"][0]["brand"] == "COMMERCIAL"


def test_commercial_requested_brand_cards_do_not_promote_wrong_section_as_anchor():
    class ApolloCommercialHTTPClient:
        def post_json(self, path, *, params=None, json_data=None):
            params = params or {}
            brand = str(params.get("b") or "")
            rim = str(params.get("rim_size") or "")
            section = str(params.get("section_width") or "")
            products = []
            if brand == "APOLLO" and rim == "R14C" and section == "195":
                products = [
                    _raw_product(201, "apollo-195-r14c", "APOLLO", "APOLLO 195/R14C ALTRUST 106/104S", "195", "", "R14C", 6730, tire_type="Mid Range")
                ]
            elif brand == "APOLLO" and rim == "R14C":
                products = [
                    _raw_product(201, "apollo-195-r14c", "APOLLO", "APOLLO 195/R14C ALTRUST 106/104S", "195", "", "R14C", 6730, tire_type="Mid Range"),
                    _raw_product(202, "apollo-185-r14c", "APOLLO", "APOLLO 185/R14C ALTRUST GRIP 102/100S", "185", "", "R14C", 6330, tire_type="Mid Range"),
                ]
            elif rim == "R14C" and section == "195":
                products = [
                    _raw_product(203, "laufenn-195-r14c", "LAUFENN", "LAUFENN 195/R14C X FIT VAN 106/104R", "195", "", "R14C", 4300, tire_type="Mid Range")
                ]
            elif rim == "R14C":
                products = [
                    _raw_product(203, "laufenn-195-r14c", "LAUFENN", "LAUFENN 195/R14C X FIT VAN 106/104R", "195", "", "R14C", 4300, tire_type="Mid Range"),
                    _raw_product(204, "deestone-195-r14c", "DEESTONE", "DEESTONE 195/R14C VAN 106/104R", "195", "", "R14C", 4100, tire_type="Economy"),
                ]
            return _category_payload(products)

        def get_json(self, path):
            return []

    runner = ProductSearchRunner(http_client=ApolloCommercialHTTPClient(), max_api_calls=8)
    result = runner.run(
        {
            "section_width": "195",
            "rim_size": "14C",
            "brands": ["Apollo"],
            "soft_preferences": ["compare alternatives"],
            "top_k": 6,
        }
    )

    slugs = [card["slug"] for card in result["product_cards"]]
    assert slugs[0] == "apollo-195-r14c"
    assert "apollo-185-r14c" not in slugs
    assert "laufenn-195-r14c" in slugs


def test_commercial_explicit_80_aspect_stays_exact():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"section_width": "195", "aspect_ratio": "80", "rim_size": "R14C", "top_k": 3})

    assert result["best_products"][0]["slug"] == "commercial-r14c-80"
    assert "aspect_ratio" in result["best_products"][0]["match"]["passed_filters"]


def test_legacy_decimal_section_width_keeps_bare_numeric_rim():
    assert normalize_section_width("7.5") == "7.50"
    assert normalize_rim_size("15", section_width="7.50") == "15"
    assert normalize_rim_size("20", section_width="8.25") == "20"

    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=4)
    result = runner.run({"section_width": "7.5", "rim_size": "15", "top_k": 3})

    assert result["status"] == "ok"
    assert result["best_products"][0]["section_width"] == "7.50"
    assert result["best_products"][0]["rim_size"] == "15"
    assert any(call["params"].get("section_width") == "7.50" for call in client.post_calls)
    assert any(call["params"].get("rim_size") == "15" for call in client.post_calls)


def test_ev_compatible_filter_uses_ev_tire_flag():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"section_width": "265", "aspect_ratio": "35", "rim_size": "ZR21", "ev_compatible": True, "top_k": 3})

    assert result["best_products"][0]["ev_compatible"] is True
    assert "ev_compatible" in result["best_products"][0]["match"]["passed_filters"]


def test_gulong_guarantee_tier_filter():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R18", "gulong_guarantee_tiers": [2], "top_k": 3})

    assert result["best_products"][0]["slug"] == "tier-two"
    assert result["best_products"][0]["gulong_guarantee"] == 2
    assert "gulong_guarantee" in result["best_products"][0]["match"]["passed_filters"]


def test_inactive_status_id_products_are_excluded():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R19", "top_k": 3})

    slugs = {product["slug"] for product in result["best_products"]}
    assert "inactive-product" not in slugs
    assert "active-product" in slugs
    assert all(product["status_id"] == 0 for product in result["best_products"])


def test_origin_warranty_and_price_category_filters_rank_matching_products():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run(
        {
            "rim_size": "R15",
            "origins": ["China"],
            "warranty_years": [1],
            "tire_categories": ["Budget"],
            "top_k": 3,
        }
    )

    top = result["best_products"][0]
    assert top["slug"] == "atlas-force"
    assert top["origin"] == "China"
    assert top["warranty_years"] == 1
    assert top["category"] == "Budget"
    assert "origin" in top["match"]["passed_filters"]
    assert "warranty_years" in top["match"]["passed_filters"]
    assert "tire_category" in top["match"]["passed_filters"]
    assert result["facets"]["origins"]
    assert result["facets"]["warranty_years"]


def test_unknown_price_category_is_ignored_not_used_as_hard_filter():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R15", "tire_categories": ["passenger"], "top_k": 3})

    assert result["query_basis"]["normalized_filters"]["tire_categories"] == []
    assert result["product_cards"]
    assert result["result_pool_summary"]["exact"] > 0


def test_all_terrain_filter_uses_catalog_fallback_without_atlas_false_positive():
    client = FakeHTTPClient()
    runner = ProductSearchRunner(http_client=client, max_api_calls=4)
    result = runner.run({"terrain_types": ["all terrain"], "top_k": 8})

    assert "/product_list" in client.get_calls
    assert result["best_products"][0]["slug"] == "yoko-geolandar"
    assert "ALL_TERRAIN" in result["best_products"][0]["terrain_types"]
    atlas = next(product for product in result["best_products"] if product["slug"] == "atlas-highway")
    assert "ALL_TERRAIN" not in atlas.get("terrain_types", [])


def test_requested_brand_exact_size_precedes_other_brand_matching_soft_filter():
    runner = ProductSearchRunner(
        http_client=NittoTerrainMismatchHTTPClient(),
        max_api_calls=8,
    )

    result = runner.run(
        {
            "section_width": "265",
            "aspect_ratio": "50",
            "rim_size": "R20",
            "required_brands": ["NITTO"],
            "terrain_types": ["ALL_TERRAIN"],
            "top_k": 4,
        }
    )

    cards = result["product_cards"]
    assert result["status"] == "partial_match"
    assert result["result_level"] == "near_exact"
    assert len(cards) == 4
    assert [card["brand"] for card in cards[:3]] == ["NITTO"] * 3
    assert cards[-1]["brand"] == "OTHER"
    assert {card["tire_size"] for card in cards} == {"265/50R20"}
    assert all(card["image_url"] for card in cards)
    assert all(card["missing_requested_filters"] == ["terrain_type"] for card in cards[:3])
    assert cards[-1]["missing_requested_filters"] == ["brand"]
    assert result["presentation_strategy"]["relaxation"] == {
        "applied": True,
        "reason": "no products matched all requested presentation filters",
        "shown_cards_missing_filters": ["terrain_type", "brand"],
    }


def test_explicit_brand_only_never_relaxes_to_another_brand_for_terrain_match():
    runner = ProductSearchRunner(
        http_client=NittoTerrainMismatchHTTPClient(),
        max_api_calls=8,
    )

    result = runner.run(
        {
            "section_width": "265",
            "aspect_ratio": "50",
            "rim_size": "R20",
            "required_brands": ["TOYO"],
            "brand_match_mode": "strict",
            "terrain_types": ["ALL_TERRAIN"],
            "top_k": 4,
        }
    )

    assert result["product_cards"] == []
    assert result["presented_products"] == []


def test_missing_requested_brand_relaxes_to_exact_size_soft_filter_match():
    runner = ProductSearchRunner(
        http_client=NittoTerrainMismatchHTTPClient(),
        max_api_calls=8,
    )

    result = runner.run(
        {
            "section_width": "265",
            "aspect_ratio": "50",
            "rim_size": "R20",
            "required_brands": ["TOYO"],
            "terrain_types": ["ALL_TERRAIN"],
            "top_k": 4,
        }
    )

    assert [card["brand"] for card in result["product_cards"]] == ["OTHER"]
    assert result["product_cards"][0]["missing_requested_filters"] == ["brand"]


def test_required_brand_relaxation_does_not_bypass_ev_compatibility():
    runner = ProductSearchRunner(
        http_client=NittoTerrainMismatchHTTPClient(),
        max_api_calls=8,
    )

    result = runner.run(
        {
            "section_width": "265",
            "aspect_ratio": "50",
            "rim_size": "R20",
            "required_brands": ["NITTO"],
            "ev_compatible": True,
            "top_k": 4,
        }
    )

    assert result["product_cards"] == []
    assert result["presented_products"] == []


def test_mud_terrain_filter_detects_mt_and_ranks_it_first():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"terrain_types": ["M/T"], "top_k": 4})

    assert result["best_products"][0]["slug"] == "bfg-km3"
    assert "MUD_TERRAIN" in result["best_products"][0]["terrain_types"]
    assert "terrain_type" in result["best_products"][0]["match"]["passed_filters"]


def test_availability_filter_can_search_pre_order_products():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run({"rim_size": "R18", "availability": "pre_order", "top_k": 3})

    top = result["best_products"][0]
    assert top["slug"] == "tier-one"
    assert top["pre_order"] is True
    assert "availability" in top["match"]["passed_filters"]
    assert result["facets"]["availability"]


def test_installment_filters_use_bank_months_and_interest_rate():
    runner = ProductSearchRunner(http_client=FakeHTTPClient(), max_api_calls=4)
    result = runner.run(
        {
            "rim_size": "R15",
            "installment_only": True,
            "installment_banks": ["BPI"],
            "installment_months": [6],
            "installment_max_interest": 0,
            "top_k": 3,
        }
    )

    top = result["best_products"][0]
    assert top["slug"] == "michelin-xm2"
    assert top["installment_text"] == "BPI 6mo 0% interest"
    assert top["installment_min_interest"] == 0
    assert "installment" in top["match"]["passed_filters"]
    assert "installment_bank" in top["match"]["passed_filters"]
    assert "installment_months" in top["match"]["passed_filters"]
    assert "installment_interest" in top["match"]["passed_filters"]
    assert result["facets"]["installment_banks"]


def test_image_backed_candidates_replace_only_incomplete_multi_card_set(monkeypatch):
    request = ProductSearchRequest(rim_size="R17", top_k=3)
    missing = {"item_ref": "missing", "brand": "BRAND A", "image_url": None}
    first = {
        "item_ref": "first",
        "brand": "BRAND B",
        "image_url": "https://storage.googleapis.com/catalog/first.webp",
    }
    second = {
        "item_ref": "second",
        "brand": "BRAND C",
        "image_url": "https://storage.googleapis.com/catalog/second.webp",
    }
    seen = []

    def select(request_arg, ranked_arg, *, limit=4):
        assert request_arg is request
        seen.extend(ranked_arg)
        return list(ranked_arg)[:limit]

    monkeypatch.setattr(product_search_module, "select_presentation_products", select)

    result = prefer_image_backed_presentation_products(
        request,
        [missing, first, second],
        selected=[missing, first],
        limit=3,
    )

    assert [item["item_ref"] for item in result] == ["first", "second"]
    assert [item["item_ref"] for item in seen] == ["first", "second"]


def test_image_backed_replacement_preserves_single_exact_product(monkeypatch):
    request = ProductSearchRequest(rim_size="R17", top_k=1)
    exact = {"item_ref": "exact", "brand": "BRAND A", "image_url": None}

    def fail_if_called(*args, **kwargs):
        raise AssertionError("single-product progression must not be reselected")

    monkeypatch.setattr(
        product_search_module,
        "select_presentation_products",
        fail_if_called,
    )

    assert prefer_image_backed_presentation_products(
        request,
        [exact],
        selected=[exact],
        limit=1,
    ) == [exact]


def test_image_backed_preference_preserves_required_brand_exact_size_options(
    monkeypatch,
):
    request = ProductSearchRequest(
        section_width="265",
        aspect_ratio="50",
        rim_size="R20",
        brands=["NITTO"],
        terrain_types=["ALL_TERRAIN"],
        top_k=3,
    )
    image_backed = {
        "item_ref": "nitto-420sd",
        "brand": "NITTO",
        "image_url": "https://storage.googleapis.com/catalog/nitto-420sd.webp",
    }
    text_only = {
        "item_ref": "nitto-terra",
        "brand": "NITTO",
        "image_url": None,
    }

    def fail_if_called(*args, **kwargs):
        raise AssertionError("required-brand exact-size options must not be reselected")

    monkeypatch.setattr(
        product_search_module,
        "select_presentation_products",
        fail_if_called,
    )

    assert prefer_image_backed_presentation_products(
        request,
        [image_backed, text_only],
        selected=[image_backed, text_only],
        limit=3,
    ) == [image_backed, text_only]

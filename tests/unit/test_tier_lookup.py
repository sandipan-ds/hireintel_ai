"""Tests for institute and certificate tier lookup."""

from src.scoring.tier_lookup import (
    get_certificate_tier_points,
    get_institute_tier_points,
    lookup_certificate_tier,
    lookup_institute_tier,
    reload_tier_databases,
)


class TestInstituteTierLookup:
    """Institute tier lookup should classify institutes deterministically."""

    def test_iit_is_tier_1(self):
        tier, points = lookup_institute_tier("IIT Bombay")
        assert tier == "tier_1"
        assert points == 1.0

    def test_nit_is_tier_1(self):
        tier, points = lookup_institute_tier("NIT Trichy")
        assert tier == "tier_1"
        assert points == 1.0

    def test_iisc_is_tier_1(self):
        tier, points = lookup_institute_tier("IISc Bangalore")
        assert tier == "tier_1"
        assert points == 1.0

    def test_iim_is_tier_1(self):
        tier, points = lookup_institute_tier("IIM Ahmedabad")
        assert tier == "tier_1"
        assert points == 1.0

    def test_mit_is_tier_1(self):
        tier, points = lookup_institute_tier("Massachusetts Institute of Technology")
        assert tier == "tier_1"
        assert points == 1.0

    def test_stanford_is_tier_1(self):
        tier, points = lookup_institute_tier("Stanford University")
        assert tier == "tier_1"
        assert points == 1.0

    def test_bits_pilani_is_tier_1(self):
        tier, points = lookup_institute_tier("BITS Pilani")
        assert tier == "tier_1"
        assert points == 1.0

    def test_isb_is_tier_1(self):
        tier, points = lookup_institute_tier("ISB Hyderabad")
        assert tier == "tier_1"
        assert points == 1.0

    def test_delhi_university_is_tier_2(self):
        tier, points = lookup_institute_tier("Delhi University")
        assert tier == "tier_2"
        assert points == 0.75

    def test_vit_vellore_is_tier_2(self):
        tier, points = lookup_institute_tier("VIT Vellore")
        assert tier == "tier_2"
        assert points == 0.75

    def test_amity_is_tier_2(self):
        tier, points = lookup_institute_tier("Amity University")
        assert tier == "tier_2"
        assert points == 0.75

    def test_dtu_is_tier_2(self):
        tier, points = lookup_institute_tier("DTU Delhi")
        assert tier == "tier_2"
        assert points == 0.75

    def test_case_insensitive(self):
        tier, points = lookup_institute_tier("iit bombay")
        assert tier == "tier_1"
        assert points == 1.0

    def test_partial_match(self):
        tier, points = lookup_institute_tier("B.Tech from IIT Madras")
        assert tier == "tier_1"
        assert points == 1.0

    def test_unknown_institute_gets_not_listed_default(self):
        tier, points = lookup_institute_tier("Some Unknown Regional College")
        assert tier is None
        assert points == 0.01

    def test_empty_name(self):
        tier, points = lookup_institute_tier("")
        assert tier is None
        assert points == 0.0

    def test_convenience_points_only(self):
        assert get_institute_tier_points("IIT Delhi") == 1.0
        assert get_institute_tier_points("VIT Vellore") == 0.75
        assert get_institute_tier_points("Unknown College") == 0.01

    def test_calcutta_university_is_tier_3(self):
        tier, points = lookup_institute_tier("University of Calcutta")
        assert tier == "tier_3"
        assert points == 0.50

    def test_osmania_is_tier_3(self):
        tier, points = lookup_institute_tier("Osmania University")
        assert tier == "tier_3"
        assert points == 0.50

    def test_bit_mesra_is_tier_3(self):
        tier, points = lookup_institute_tier("BIT Mesra")
        assert tier == "tier_3"
        assert points == 0.50

    def test_tifr_is_tier_3(self):
        tier, points = lookup_institute_tier("Tata Institute of Fundamental Research")
        assert tier == "tier_3"
        assert points == 0.50

    def test_andhra_university_is_tier_3(self):
        tier, points = lookup_institute_tier("Andhra University")
        assert tier == "tier_3"
        assert points == 0.50


class TestCertificateTierLookup:
    """Certificate tier lookup should classify certifications deterministically."""

    def test_aws_saa_is_tier_1(self):
        tier, points = lookup_certificate_tier("AWS Solutions Architect Associate")
        assert tier == "tier_1"
        assert points == 1.0

    def test_azure_administrator_is_tier_1(self):
        tier, points = lookup_certificate_tier("Microsoft Certified: Azure Administrator Associate")
        assert tier == "tier_1"
        assert points == 1.0

    def test_pmp_is_tier_1(self):
        tier, points = lookup_certificate_tier("PMP Certification")
        assert tier == "tier_1"
        assert points == 1.0

    def test_cissp_is_tier_1(self):
        tier, points = lookup_certificate_tier("CISSP")
        assert tier == "tier_1"
        assert points == 1.0

    def test_tableau_is_tier_1(self):
        tier, points = lookup_certificate_tier("Tableau Desktop Certified Associate")
        assert tier == "tier_1"
        assert points == 1.0

    def test_power_bi_is_tier_1(self):
        tier, points = lookup_certificate_tier("Microsoft Power BI Certification")
        assert tier == "tier_1"
        assert points == 1.0

    def test_iit_pg_certificate_is_tier_1(self):
        tier, points = lookup_certificate_tier("IIT PG Certificate in Data Science")
        assert tier == "tier_1"
        assert points == 1.0

    def test_stanford_online_is_tier_1(self):
        tier, points = lookup_certificate_tier("Stanford Online Certificate in AI")
        assert tier == "tier_1"
        assert points == 1.0

    def test_coursera_is_tier_2(self):
        tier, points = lookup_certificate_tier("Coursera Specialization in Deep Learning")
        assert tier == "tier_2"
        assert points == 0.75

    def test_nptel_is_tier_2(self):
        tier, points = lookup_certificate_tier("NPTEL Certification in Data Structures")
        assert tier == "tier_2"
        assert points == 0.75

    def test_udacity_is_tier_2(self):
        tier, points = lookup_certificate_tier("Udacity Nanodegree in Machine Learning")
        assert tier == "tier_2"
        assert points == 0.75

    def test_google_career_certificate_is_tier_2(self):
        tier, points = lookup_certificate_tier("Google Data Analytics Certificate")
        assert tier == "tier_2"
        assert points == 0.75

    def test_bootcamp_is_tier_3(self):
        tier, points = lookup_certificate_tier("Coding Bootcamp Certificate")
        assert tier == "tier_3"
        assert points == 0.50

    def test_workshop_is_tier_3(self):
        tier, points = lookup_certificate_tier("Workshop Certificate on Python")
        assert tier == "tier_3"
        assert points == 0.50

    def test_unknown_certificate_gets_not_listed_default(self):
        tier, points = lookup_certificate_tier("Some Random Local Certificate")
        assert tier is None
        assert points == 0.01

    def test_empty_name(self):
        tier, points = lookup_certificate_tier("")
        assert tier is None
        assert points == 0.0

    def test_convenience_points_only(self):
        assert get_certificate_tier_points("AWS Solutions Architect Associate") == 1.0
        assert get_certificate_tier_points("Coursera Specialization") == 0.75
        assert get_certificate_tier_points("Unknown Certificate") == 0.01

    def test_red_hat_rhcsa_is_tier_2(self):
        tier, points = lookup_certificate_tier("RHCSA - Red Hat Certified System Administrator")
        assert tier == "tier_2"
        assert points == 0.75

    def test_cka_kubernetes_is_tier_1(self):
        tier, points = lookup_certificate_tier("Certified Kubernetes Administrator (CKA)")
        assert tier == "tier_1"
        assert points == 1.0

    def test_prince2_is_tier_1(self):
        tier, points = lookup_certificate_tier("PRINCE2 Foundation Certification")
        assert tier == "tier_1"
        assert points == 1.0

    def test_cfa_level_1_is_tier_1(self):
        tier, points = lookup_certificate_tier("CFA Level 1")
        assert tier == "tier_1"
        assert points == 1.0

    def test_sap_certified_is_tier_1(self):
        tier, points = lookup_certificate_tier("SAP HANA Certified")
        assert tier == "tier_1"
        assert points == 1.0

    def test_salesforce_admin_is_tier_1(self):
        tier, points = lookup_certificate_tier("Salesforce Certified Administrator")
        assert tier == "tier_1"
        assert points == 1.0

    def test_rhce_is_tier_2(self):
        tier, points = lookup_certificate_tier("RHCE - Red Hat Certified Engineer")
        assert tier == "tier_2"
        assert points == 0.75

    def test_tensorflow_certificate_is_tier_2(self):
        tier, points = lookup_certificate_tier("TensorFlow Developer Certificate")
        assert tier == "tier_2"
        assert points == 0.75

    def test_chartered_accountant_is_tier_1(self):
        tier, points = lookup_certificate_tier("Chartered Accountant India")
        assert tier == "tier_1"
        assert points == 1.0

    def test_kaggle_is_tier_2(self):
        tier, points = lookup_certificate_tier("Kaggle Learn Certificate")
        assert tier == "tier_2"
        assert points == 0.75

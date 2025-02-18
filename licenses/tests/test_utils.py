# Standard library
import os
import tempfile
from io import StringIO
from unittest import mock
from unittest.mock import MagicMock, call

# Third-party
from bs4 import BeautifulSoup
from django.test import TestCase
from django.urls import Resolver404, URLResolver
from polib import POEntry

# First-party/Local
from licenses.models import License
from licenses.utils import (
    clean_string,
    cleanup_current_branch_output,
    compute_about_url,
    get_code_from_jurisdiction_url,
    get_license_url_from_legalcode_url,
    parse_legalcode_filename,
    relative_symlink,
    save_bytes_to_file,
    save_dict_to_pofile,
    save_url_as_static_file,
    strip_list_whitespace,
    validate_dictionary_is_all_text,
    validate_list_is_all_text,
)
from .factories import LegalCodeFactory, LicenseFactory


class SaveURLAsStaticFileTest(TestCase):
    def test_save_bytes_to_file(self):
        try:
            tmpdir = tempfile.TemporaryDirectory()
            filename = os.path.join(tmpdir.name, "level1")
            save_bytes_to_file(b"abcxyz", filename)
            with open(filename, "rb") as f:
                contents = f.read()
            self.assertEqual(b"abcxyz", contents)

            filename = os.path.join(tmpdir.name, "level1", "level2")
            save_bytes_to_file(b"abcxyz", filename)
            with open(filename, "rb") as f:
                contents = f.read()
            self.assertEqual(b"abcxyz", contents)
        finally:
            tmpdir.cleanup()

    def test_relative_symlink(self):
        try:
            tmpdir = tempfile.TemporaryDirectory()
            # symlink link1 => source1 and verify by reading link1
            contents1 = b"111"
            source1 = os.path.join(tmpdir.name, "source1")
            with open(source1, "wb") as f:
                f.write(contents1)
            with mock.patch("sys.stdout", new=StringIO()) as mock_out:
                relative_symlink(tmpdir.name, source1, "link1")
                self.assertEqual(mock_out.getvalue().strip(), "^link1")
            with open(os.path.join(tmpdir.name, "link1"), "rb") as f:
                contents = f.read()
            self.assertEqual(contents1, contents)
            # symlink link2 => xx/source2 and verify by reading link2
            subdir = os.path.join(tmpdir.name, "xx")
            os.makedirs(subdir, mode=0o755)
            contents2 = b"222"
            source2 = os.path.join(subdir, "source1")
            with open(source2, "wb") as f:
                f.write(contents2)
            with mock.patch("sys.stdout", new=StringIO()) as mock_out:
                relative_symlink(tmpdir.name, source2, "../link2")
                self.assertEqual(mock_out.getvalue().strip(), "^link2")
            with open(os.path.join(tmpdir.name, "link2"), "rb") as f:
                contents = f.read()
            self.assertEqual(contents2, contents)
        finally:
            tmpdir.cleanup()

    def test_save_url_as_static_file_not_200(self):
        output_dir = "/output"
        url = "/some/url/"
        with self.assertRaises(Resolver404):
            save_url_as_static_file(output_dir, url, "")

    def test_save_url_as_static_file_500(self):
        output_dir = "/output"
        url = "/licenses/metadata.yaml"
        file_content = b"xxxxx"

        class MockResponse:
            content = file_content
            status_code = 500

        class MockResolverMatch:
            def __init__(self, func):
                self.func = func
                self.args = []
                self.kwargs = {}

        mock_metadata_view = MagicMock()
        mock_metadata_view.return_value = MockResponse()

        with mock.patch("licenses.utils.save_bytes_to_file"):
            with mock.patch.object(URLResolver, "resolve") as mock_resolve:
                mock_resolve.return_value = MockResolverMatch(
                    func=mock_metadata_view
                )
                with self.assertRaisesMessage(
                    ValueError,
                    "ERROR: Status 500 for url /licenses/metadata.yaml",
                ):
                    save_url_as_static_file(
                        output_dir, url, "/output/licenses/metadata.yaml"
                    )

    def test_save_url_as_static_file_home(self):
        """
        home is a TemplateView, which needs to be rendered before
        we can look at its content?
        """
        output_dir = "/output"
        url = "/"

        with mock.patch("licenses.utils.save_bytes_to_file"):
            with mock.patch("sys.stdout", new=StringIO()) as mock_out:
                save_url_as_static_file(output_dir, url, "/output/home.html")
                self.assertEqual(
                    mock_out.getvalue().strip(), "/output/home.html"
                )

    def test_save_url_as_static_file_200(self):
        output_dir = "/output"
        url = "/licenses/metadata.yaml"
        file_content = b"xxxxx"
        relpath = "licenses/metadata.yaml"

        class MockResponse:
            content = file_content
            status_code = 200

        class MockResolverMatch:
            def __init__(self, func):
                self.func = func
                self.args = []
                self.kwargs = {}

        mock_metadata_view = MagicMock()
        mock_metadata_view.return_value = MockResponse()

        with mock.patch("licenses.utils.save_bytes_to_file") as mock_save:
            with mock.patch.object(URLResolver, "resolve") as mock_resolve:
                mock_resolve.return_value = MockResolverMatch(
                    func=mock_metadata_view
                )
                with mock.patch("sys.stdout", new=StringIO()) as mock_out:
                    save_url_as_static_file(output_dir, url, relpath)
                    self.assertEqual(
                        mock_out.getvalue().strip(), "licenses/metadata.yaml"
                    )

        self.assertEqual([call(url)], mock_resolve.call_args_list)
        self.assertEqual(
            [call(request=mock.ANY)], mock_metadata_view.call_args_list
        )
        self.assertEqual(
            [call(file_content, "/output/licenses/metadata.yaml")],
            mock_save.call_args_list,
        )


class GetJurisdictionCodeTest(TestCase):
    def test_get_code_from_jurisdiction_url(self):
        # Just returns the last portion of the path
        self.assertEqual(
            "foo",
            get_code_from_jurisdiction_url("http://example.com/bar/foo/"),
        )
        self.assertEqual(
            "foo", get_code_from_jurisdiction_url("http://example.com/bar/foo")
        )
        self.assertEqual(
            "", get_code_from_jurisdiction_url("http://example.com")
        )


class ParseLegalcodeFilenameTest(TestCase):
    # Test parse_legalcode_filename
    def test_parse_legalcode_filename(self):
        data = [
            (
                "by_1.0.html",
                {
                    "about_url": (
                        "https://creativecommons.org/licenses/by/1.0/"
                    ),
                    "license_code": "by",
                    "version": "1.0",
                    "jurisdiction_code": "",
                    "cc_language_code": "en",
                    "category": "licenses",
                },
            ),
            (
                "by_3.0_es_ast",
                {
                    "about_url": (
                        "https://creativecommons.org/licenses/by/3.0/es/"
                    ),
                    "license_code": "by",
                    "version": "3.0",
                    "jurisdiction_code": "es",
                    "cc_language_code": "ast",
                    "category": "licenses",
                },
            ),
            (
                "by_3.0_rs_sr-Cyrl.html",
                {
                    "about_url": (
                        "https://creativecommons.org/licenses/by/3.0/rs/"
                    ),
                    "license_code": "by",
                    "version": "3.0",
                    "jurisdiction_code": "rs",
                    "cc_language_code": "sr-Cyrl",
                    "category": "licenses",
                },
            ),
            (
                "devnations_2.0.html",
                {
                    "about_url": (
                        "https://creativecommons.org/licenses/devnations/2.0/"
                    ),
                    "license_code": "devnations",
                    "version": "2.0",
                    "jurisdiction_code": "",
                    "cc_language_code": "en",
                    "category": "licenses",
                },
            ),
            (
                "LGPL_2.1.html",
                {
                    "about_url": (
                        "https://creativecommons.org/licenses/LGPL/2.1/"
                    ),
                    "license_code": "LGPL",
                    "version": "2.1",
                    "jurisdiction_code": "",
                    "cc_language_code": "en",
                    "category": "licenses",
                },
            ),
            (
                "samplingplus_1.0",
                {
                    "about_url": (
                        "https://creativecommons.org/licenses/sampling+/1.0/"
                    ),
                    "license_code": "sampling+",
                    "version": "1.0",
                    "jurisdiction_code": "",
                    "cc_language_code": "en",
                    "category": "licenses",
                },
            ),
            (
                "zero_1.0_fi.html",
                {
                    "about_url": (
                        "https://creativecommons.org/publicdomain/zero/1.0/"
                    ),
                    "license_code": "CC0",
                    "version": "1.0",
                    "jurisdiction_code": "",
                    "cc_language_code": "fi",
                    "category": "publicdomain",
                },
            ),
            (
                "nc-samplingplus_1.0.html",
                {
                    "about_url": (
                        "https://creativecommons.org/licenses/nc-sampling+/"
                        "1.0/"
                    ),
                    "license_code": "nc-sampling+",
                    "version": "1.0",
                    "jurisdiction_code": "",
                    "cc_language_code": "en",
                    "category": "licenses",
                },
            ),
        ]
        for filename, expected_result in data:
            with self.subTest(filename):
                result = parse_legalcode_filename(filename)
                if result != expected_result:
                    print(repr(result))
                self.assertEqual(expected_result, result)
        with self.assertRaisesMessage(ValueError, "Invalid language_code="):
            parse_legalcode_filename("by_3.0_es_aaa")
        with self.assertRaisesMessage(ValueError, "What language? "):
            parse_legalcode_filename("by_3.0_zz")


class GetLicenseURLFromLegalCodeURLTest(TestCase):
    # get_license_url_from_legalcode_url
    def test_get_license_url_from_legalcode_url(self):
        data = [
            (
                "https://creativecommons.org/licenses/by/4.0/legalcode",
                "https://creativecommons.org/licenses/by/4.0/",
            ),
            (
                "https://creativecommons.org/licenses/by/4.0/legalcode.es",
                "https://creativecommons.org/licenses/by/4.0/",
            ),
            (
                "https://creativecommons.org/licenses/GPL/2.0/legalcode",
                "https://creativecommons.org/licenses/GPL/2.0/",
            ),
            (
                "https://creativecommons.org/licenses/nc-sampling+/1.0/tw/"
                "legalcode",
                "https://creativecommons.org/licenses/nc-sampling+/1.0/tw/",
            ),
            # Exceptions:
            (
                "http://opensource.org/licenses/bsd-license.php",
                "https://creativecommons.org/licenses/BSD/",
            ),
            (
                "http://opensource.org/licenses/mit-license.php",
                "https://creativecommons.org/licenses/MIT/",
            ),
        ]
        for legalcode_url, expected_license_url in data:
            with self.subTest(legalcode_url):
                self.assertEqual(
                    expected_license_url,
                    get_license_url_from_legalcode_url(legalcode_url),
                )
        with self.assertRaises(ValueError):
            get_license_url_from_legalcode_url(
                "http://opensource.org/licences/bsd-license.php"
            )


class GetLicenseUtilityTest(TestCase):
    """Test django-distill utility functions for
    generating an iterable of license dictionaries
    """

    def setUp(self):
        self.license1 = LicenseFactory(license_code="by", version="4.0")
        self.license2 = LicenseFactory(license_code="by-nc", version="4.0")
        self.license3 = LicenseFactory(
            license_code="by-nd", version="3.0", jurisdiction_code="hk"
        )
        self.license4 = LicenseFactory(
            license_code="by-nc-sa", version="3.0", jurisdiction_code="us"
        )
        self.license5 = LicenseFactory(
            license_code="by-na", version="3.0", jurisdiction_code="nl"
        )
        self.license6 = LicenseFactory(license_code="by", version="")  # zero
        self.license7 = LicenseFactory(license_code="by", version="2.5")
        self.license8 = LicenseFactory(license_code="by", version="2.0")
        self.license9 = LicenseFactory(license_code="by", version="2.1")

        for license in License.objects.all():
            LegalCodeFactory(license=license, language_code="en")
            LegalCodeFactory(license=license, language_code="fr")


class TestComputeAboutURL(TestCase):
    def test_by_nc_40(self):
        self.assertEqual(
            "https://creativecommons.org/licenses/by-nc/4.0/",
            compute_about_url(
                category="licenses",
                license_code="by-nc",
                version="4.0",
                jurisdiction_code="",
            ),
        )

    def test_bsd(self):
        self.assertEqual(
            "https://creativecommons.org/licenses/BSD/",
            compute_about_url(
                category="licenses",
                license_code="BSD",
                version="",
                jurisdiction_code="",
            ),
        )

    def test_mit(self):
        self.assertEqual(
            "https://creativecommons.org/licenses/MIT/",
            compute_about_url(
                category="licenses",
                license_code="MIT",
                version="",
                jurisdiction_code="",
            ),
        )

    def test_gpl20(self):
        self.assertEqual(
            "https://creativecommons.org/licenses/GPL/2.0/",
            compute_about_url(
                category="licenses",
                license_code="GPL",
                version="2.0",
                jurisdiction_code="",
            ),
        )

    def test_30_nl(self):
        self.assertEqual(
            "https://creativecommons.org/licenses/by/3.0/nl/",
            compute_about_url(
                category="licenses",
                license_code="by",
                version="3.0",
                jurisdiction_code="nl",
            ),
        )


class TestMisc(TestCase):
    def test_validate_list_is_all_text(self):
        validate_list_is_all_text(["a", "b"])
        with self.assertRaises(ValueError):
            validate_list_is_all_text(["a", 1])
        with self.assertRaises(ValueError):
            validate_list_is_all_text(["a", 4.2])
        with self.assertRaises(ValueError):
            validate_list_is_all_text(["a", object()])
        soup = BeautifulSoup("<span>foo</span>", "lxml")
        navstring = soup.span.string
        out = validate_list_is_all_text([navstring])
        self.assertEqual(["foo"], out)
        self.assertEqual([["foo"]], validate_list_is_all_text([[navstring]]))
        self.assertEqual(
            [{"a": "foo"}], validate_list_is_all_text([{"a": navstring}])
        )

    def test_validate_dictionary_is_all_text(self):
        validate_dictionary_is_all_text({"1": "a", "2": "b"})
        with self.assertRaises(ValueError):
            validate_dictionary_is_all_text({"1": "a", "2": 1})
        with self.assertRaises(ValueError):
            validate_dictionary_is_all_text({"1": "a", "2": 3.14})
        with self.assertRaises(ValueError):
            validate_dictionary_is_all_text({"1": "a", "2": object()})
        soup = BeautifulSoup("<span>foo</span>", "lxml")
        navstring = soup.span.string
        self.assertEqual(
            {"a": "foo"}, validate_dictionary_is_all_text({"a": navstring})
        )
        self.assertEqual(
            {"a": ["foo"]}, validate_dictionary_is_all_text({"a": [navstring]})
        )
        self.assertEqual(
            {"a": {"b": "foo"}},
            validate_dictionary_is_all_text({"a": {"b": "foo"}}),
        )

    def test_save_dict_to_pofile(self):
        mock_pofile = MagicMock()
        mock_pofile.append = MagicMock()
        messages = {"a": "one", "b": "two"}
        save_dict_to_pofile(mock_pofile, messages)
        self.assertEqual([], mock_pofile.call_args_list)
        self.assertEqual(2, len(mock_pofile.append.call_args_list))
        args, kwargs = mock_pofile.append.call_args_list[0]
        self.assertTrue(isinstance(args[0], POEntry))

    def test_strip_list_whitespace(self):
        expected_list = ["left", "right", "center"]
        left_list = [" left", " right", " center"]
        right_list = ["left ", "right ", "center "]
        center_list = [" left ", " right ", " center "]
        self.assertEqual(
            strip_list_whitespace("left", left_list), expected_list
        )
        self.assertEqual(
            strip_list_whitespace("right", right_list), expected_list
        )
        self.assertEqual(
            strip_list_whitespace("center", center_list), expected_list
        )

    def test_cleanup_current_branch_output(self):
        expected_list = ["some-branch", "another-branch", "main"]
        unmodified_list = ["some-branch", "* another-branch", "main"]
        self.assertEqual(
            cleanup_current_branch_output(unmodified_list), expected_list
        )


class CleanStringTest(TestCase):
    def test_clean_string(self):
        data = [
            # input, expected result
            ("foo", "foo"),
            ("foo bar", "foo bar"),
            ("foo  bar", "foo bar"),
            ("foo   bar", "foo bar"),
            (" x ", "x"),
            ("one\ntwo", "one two"),
        ]
        for input, expected in data:
            with self.subTest(input):
                self.assertEqual(expected, clean_string(input))

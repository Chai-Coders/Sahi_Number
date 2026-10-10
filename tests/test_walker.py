from sahi.extract.walker import walk_response


def test_walks_each_surface_and_ignores_metadata_urls_and_identifiers():
    body = {
        "search_metadata": {"id": "9999999999", "status": "Success"},
        "search_parameters": {"q": "Example Air 8888888888"},
        "organic_results": [
            {
                "position": 1,
                "title": "Unofficial help",
                "link": "https://help.example.test/page/9876543210",
                "snippet": "Call 98765 43210",
                "data_id": "12345678901234567890",
            }
        ],
        "answer_box": {"title": "Answer", "answer": "Toll free 1800 123 456"},
        "knowledge_graph": {"title": "Example Air", "sales": "011 2345 6789"},
        "local_results": {
            "places": [
                {
                    "position": 2,
                    "title": "Example Air office",
                    "links": {"phone": "tel:+91-98765-43211"},
                    "rating": 4.9,
                    "reviews": 123456,
                }
            ]
        },
        "ads": [
            {
                "position": 1,
                "title": "Sponsored help",
                "link": "https://ads.example.test",
                "description": "Call 1860 123 4567",
            }
        ],
        "related_questions": [{"question": "Helpline?", "snippet": "Dial 1930"}],
        "ai_overview": {"text_blocks": [{"snippet": "Try 1800-765-4321"}]},
        "pagination": {"next": "https://google.test/start=1234567890"},
    }

    sightings = walk_response(body, receipt_id=42, engine="google")
    pairs = {(item.canonical, item.surface) for item in sightings}

    assert ("+919876543210", "ORGANIC") in pairs
    assert ("1800123456", "ANSWER_BOX") in pairs
    assert ("+911123456789", "KNOWLEDGE_GRAPH") in pairs
    assert ("+919876543211", "LOCAL_PACK") in pairs
    assert ("18601234567", "AD") in pairs
    assert ("1930", "RELATED_QUESTION") in pairs
    assert ("18007654321", "AI_OVERVIEW") in pairs
    assert all(item.receipt_id == 42 for item in sightings)
    assert all("search_metadata" not in item.json_path for item in sightings)
    assert all(item.raw != "9999999999" for item in sightings)

    organic = next(item for item in sightings if item.surface == "ORGANIC")
    assert organic.json_path == "organic_results[0].snippet"
    assert organic.title == "Unofficial help"
    assert organic.link == "https://help.example.test/page/9876543210"
    assert organic.domain == "example.test"
    assert organic.position == 1


def test_google_maps_results_are_labelled_as_maps_listings():
    body = {
        "local_results": [
            {
                "position": 1,
                "title": "Example Air",
                "phone": "98765 43210",
                "website": "https://example-air.test",
            }
        ]
    }

    sightings = walk_response(body, receipt_id=7, engine="google_maps")

    assert len(sightings) == 1
    assert sightings[0].surface == "MAPS_LISTING"
    assert sightings[0].json_path == "local_results[0].phone"

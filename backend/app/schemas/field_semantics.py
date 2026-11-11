"""Output concepts, not strings required to occur in a document.

Definitions describe the existing application's field meanings for semantic
normalization. No aliases, translated captions, values or layouts belong here.
"""

FIELD_MEANINGS = {
    "document_number": "The unique identifier assigned to this travel document.",
    "emirates_id_number": "The holder's identity number in the Emirates identity system.",
    "national_id_number": "The person's identifier in a national identity register.",
    "surname": "The family component of a person's name, inherited or shared with relatives.",
    "given_names": "The personal names given to a person, excluding their family name.",
    "first_name": "The first personal name of the holder, excluding further personal names.",
    "full_name": "The complete name of the person, including all personal and family components.",
    "middle_names": "The additional personal names between the first personal and family names.",
    "nationality": "The citizenship or national affiliation of the person.",
    "issuing_country": "The sovereign state or international organization that issued the document.",
    "country_code": "The abbreviated code identifying the state that issued the document.",
    "date_of_birth": "The calendar day, month and year when the person was born.",
    "place_of_birth": "The geographical locality where the person was born.",
    "sex": "The person's recorded sex or gender designation.",
    "date_of_issue": "The calendar date when the document was issued.",
    "date_of_expiry": "The calendar date when the document ceases to be valid.",
    "issuing_authority": "The official office or administrative body responsible for issuing the document.",
    "occupation": "The person's profession, trade or kind of work.",
    "employer": "The organization or person for whom the holder works.",
    "place_of_issue": "The geographical locality where the document was issued.",
    "personal_number": "An identifying number assigned to the person rather than the document.",
    "authority_code": "A code identifying the administrative office that issued the document.",
    "card_number": "The unique identifier assigned to the physical card.",
    "previous_passport_number": "The identifier of an earlier passport held by the person.",
    "file_number": "The identifier assigned to the administrative record or case file.",
    "book_number": "The serial identifier of the document booklet.",
    "father_name": "The name of the person's father.",
    "mother_name": "The name of the person's mother.",
    "spouse_name": "The name of the person to whom the holder is married.",
    "contact_relationship": "How a designated contact person is related to the holder.",
    "permanent_address": "The person's permanent residential postal address.",
    "address": "The postal location at which the person resides or receives correspondence.",
    "telephone_number": "The number used to contact the person by telephone.",
    "document_code": "The abbreviated designation of the document's category or type.",
    "place_of_origin": "The locality from which the person or their family originates.",
}

PRIMARY_FIELDS = frozenset(tuple(FIELD_MEANINGS)[:17])

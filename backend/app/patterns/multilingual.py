"""Explicit document-caption semantics, independent of OCR model and country.

Aliases describe fields, never values. Ambiguous civil concepts (e.g. Japanese
registered domicile versus birthplace) deliberately are not treated as synonyms.
Extend this registry when adding a language; the matcher handles every field.
"""

MULTILINGUAL_LABELS: dict[str, tuple[str, ...]] = {
    "document_number": (
        "Reisepassnummer", "Passnummer", "numéro de passeport", "numero di passaporto",
        "número de pasaporte", "número do passaporte", "número do documento",
        "护照号码", "護照號碼", "证件号码", "旅券番号", "パスポート番号",
    ),
    "national_id_number": (
        "Personalausweisnummer", "numéro d'identité", "numero di identità",
        "número de identidad", "número de identidade", "身份证号码", "身分證字號",
        "個人番号",
    ),
    "emirates_id_number": ("رقم الهوية الإماراتية",),
    "surname": ("Familienname", "Nachname", "apelido", "sobrenome", "姓"),
    "given_names": ("nomes próprios", "nombre", "الأسماء", "名"),
    "full_name": ("vollständiger Name", "nom complet", "nome completo", "nombre completo", "姓名", "氏名"),
    "middle_names": ("zweiter Vorname", "deuxième prénom", "secondo nome", "segundo nombre", "nome do meio", "الاسم الأوسط", "中间名", "ミドルネーム"),
    "nationality": ("国籍", "國籍"),
    "issuing_country": ("país de emissão", "بلد الإصدار", "签发国", "簽發國", "発行国"),
    "country_code": ("codice del paese", "código do país", "国家代码", "國家代碼", "国名コード"),
    "date_of_birth": ("data de nascimento", "出生日期", "出生年月日", "生年月日"),
    "place_of_birth": (
        "Geburtsort", "luogo di nascita", "local de nascimento", "lugar de nascimento",
        "محل الميلاد", "出生地", "出生地点", "出生場所",
    ),
    "sex": ("Geschlecht", "sesso", "性别", "性別"),
    "date_of_issue": (
        "Ausstellungsdatum", "date d'émission", "data di rilascio", "data de emissão",
        "data de expedição", "签发日期", "簽發日期", "発行年月日", "発行日", "交付年月日",
    ),
    "date_of_expiry": (
        "gültig bis", "Ablaufdatum", "data di scadenza", "data de validade",
        "有效期至", "有效期限", "有効期限", "有効期間満了日",
    ),
    "issuing_authority": (
        "autorità di rilascio", "autoridade emissora", "autoridade emitente",
        "órgão expedidor", "签发机关", "簽發機關", "発行官庁", "発行機関",
    ),
    "place_of_origin": (
        "Luogo di attinenza", "lugar de origen", "local de origem", "مكان الأصل",
        "lieu d’origine", "place of origin",
    ),
    "place_of_issue": ("local de emissão", "local de expedição", "签发地点", "簽發地點", "発行地"),
    "occupation": ("Beruf", "professione", "profesión", "profissão", "职业", "職業"),
    "employer": ("Arbeitgeber", "employeur", "datore di lavoro", "empleador", "empregador", "雇主", "勤務先"),
    "personal_number": ("Personennummer", "numéro personnel", "numero personale", "número personal", "número pessoal", "الرقم الشخصي", "个人号码", "個人識別番号"),
    "authority_code": ("codice autorità", "código da autoridade", "签发机关代码", "発行機関コード"),
    "card_number": ("Kartennummer", "numéro de carte", "numero della carta", "número de tarjeta", "número do cartão", "رقم البطاقة", "卡号", "カード番号"),
    "previous_passport_number": ("frühere Passnummer", "numéro du passeport précédent", "numero del passaporto precedente", "número de pasaporte anterior", "número do passaporte anterior", "رقم جواز السفر السابق", "原护照号码", "旧旅券番号"),
    "file_number": ("Aktenzeichen", "numero di pratica", "número de expediente", "número do processo", "رقم الملف", "档案编号", "ファイル番号"),
    "book_number": ("Buchnummer", "numéro de livret", "numero del libretto", "número de libreta", "número do livro", "رقم الدفتر", "簿册编号", "冊子番号"),
    "father_name": ("Name des Vaters", "nom du père", "nome del padre", "nombre del padre", "nome do pai", "اسم الأب", "父亲姓名", "父の氏名"),
    "mother_name": ("Name der Mutter", "nom de la mère", "nome della madre", "nombre de la madre", "nome da mãe", "اسم الأم", "母亲姓名", "母の氏名"),
    "spouse_name": ("Name des Ehepartners", "nom du conjoint", "nome del coniuge", "nombre del cónyuge", "nome do cônjuge", "اسم الزوج", "اسم الزوجة", "配偶姓名", "配偶者の氏名"),
    "contact_relationship": ("Verwandtschaftsverhältnis", "lien de parenté", "parentela", "parentesco", "صلة القرابة", "与本人关系", "続柄"),
    "permanent_address": ("ständiger Wohnsitz", "adresse permanente", "indirizzo permanente", "domicilio permanente", "endereço permanente", "العنوان الدائم", "永久住址", "定住所"),
    "address": ("Anschrift", "Adresse", "indirizzo", "dirección", "endereço", "العنوان", "住址", "住所"),
    "telephone_number": ("Telefonnummer", "numéro de téléphone", "numero di telefono", "número de teléfono", "número de telefone", "رقم الهاتف", "电话号码", "電話番号"),
    "document_code": ("Dokumententyp", "type de document", "tipo di documento", "tipo de documento", "نوع الوثيقة", "证件类型", "旅券の種類"),
}

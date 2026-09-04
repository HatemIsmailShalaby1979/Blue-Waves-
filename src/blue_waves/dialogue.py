"""Two-voice, multi-language dialogue generation for Blue Waves podcasts.

Blue Waves podcasts must ALWAYS use two distinct voices (a host and a guest).
When the caller supplies only a topic, this module expands it into a structured
host/guest conversation in the requested language, sized to fill the requested
duration instead of leaving long stretches of silence.

The prose is deliberately generic and template driven. No LLM is configured in
this deployment, so inventing specific facts about a topic would be fabrication.
The dialogue stays on-topic and conversational without asserting claims.

Templates use a single ``{topic}`` placeholder.
"""

from __future__ import annotations

from typing import Any


def _pick(seq: list[str], index: int) -> str:
    return seq[index % len(seq)]


LANGUAGE_PACKS: dict[str, dict[str, Any]] = {
    "en": {
        "label": "English",
        "host": "21m00Tcm4TlvDq8ikWAM",
        "guest": "EXAVITQu4vr4xnSDxMaL",
        "wps": 2.6,
        "t": {
            "open": [
                "Welcome back to the show. Today we are taking a close look at {topic}.",
                "Hello everyone, and thanks for joining us. Our topic today is {topic}.",
            ],
            "intro": [
                "With me in the studio is our guest, who has spent years working on {topic}.",
                "Joining me today is a specialist who knows {topic} inside and out.",
            ],
            "hello": [
                "Thanks for having me. I am glad we are finally talking about {topic}.",
                "Great to be here. {topic} is something I care about a lot.",
            ],
            "ask": [
                "So let us start simple. What exactly is {topic}?",
                "How would you explain {topic} to someone hearing about it for the first time?",
                "Why does {topic} matter right now?",
                "What is the biggest misunderstanding people have about {topic}?",
            ],
            "answer": [
                "At its core, {topic} comes down to a few simple ideas that people often overcomplicate.",
                "The short answer is that {topic} affects far more of our daily lives than most people realise.",
                "I would say {topic} is best understood by looking at how it works in practice.",
            ],
            "react": [
                "That is a really helpful way to put it.",
                "That makes a lot of sense, and it matches what I have read about {topic}.",
                "Interesting, I had not thought about {topic} in those terms before.",
            ],
            "example": [
                "For example, when people first encounter {topic}, they usually notice a change within a few weeks.",
                "A concrete case is a small team that took {topic} seriously and rebuilt their routine around it.",
                "Think about {topic} the way you would think about learning any new skill: slowly at first, then all at once.",
            ],
            "takeaway": [
                "If you remember one thing about {topic}, let it be this: start small and stay consistent.",
                "The main takeaway is that {topic} rewards patience far more than intensity.",
            ],
            "close": [
                "That is all the time we have today. Thank you for listening, and we will see you in the next episode about {topic}.",
                "We will leave it there. Thanks for joining us for this conversation on {topic}.",
            ],
        },
    },
    "ar": {
        "label": "Arabic",
        "host": "ar-SA-ZariyahNeural",
        "guest": "ar-SA-HamedNeural",
        "wps": 2.4,
        "t": {
            "open": [
                "أهلاً بكم في حلقة جديدة. موضوعنا اليوم هو {topic}.",
                "مرحباً بكم، ويسعدنا أن نستعرض معكم اليوم موضوع {topic}.",
            ],
            "intro": [
                "ينضم إلينا في الاستوديو ضيفنا الذي أمضى سنوات في العمل على {topic}.",
                "يشاركنا اليوم متخصص يعرف {topic} بشكل عميق.",
            ],
            "hello": [
                "شكراً على الاستضافة. يسعدني أن نتحدث أخيراً عن {topic}.",
                "سعيد بوجودي هنا. موضوع {topic} يهمّني كثيراً.",
            ],
            "ask": [
                "لنبدأ ببساطة: ما هو {topic} بالضبط؟",
                "كيف تشرح {topic} لشخص يسمع عنه للمرة الأولى؟",
                "لماذا يكتسب {topic} أهمية الآن؟",
                "ما هو أكبر سوء فهم شائع حول {topic}؟",
            ],
            "answer": [
                "في جوهره، يعتمد {topic} على أفكار بسيطة كثيراً ما نعقّدها.",
                "الإجابة المختصرة هي أن {topic} يؤثر في حياتنا اليومية أكثر مما نتصور.",
                "أفضل طريقة لفهم {topic} هي النظر إلى كيفية عمله على أرض الواقع.",
            ],
            "react": [
                "هذه طريقة واضحة جداً لعرض الفكرة.",
                "كلام منطقي للغاية، ويتماشى مع ما قرأته عن {topic}.",
                "مثير للاهتمام، لم أفكر في {topic} من هذا المنظور من قبل.",
            ],
            "example": [
                "على سبيل المثال، عندما يتعرف الناس على {topic}، عادة ما يلاحظون فرقاً خلال أسابيع قليلة.",
                "خذ حالة فريق صغير أخذ {topic} بجدية وأعاد تنظيم روتينه بالكامل.",
                "تعامل مع {topic} كما تتعامل مع تعلّم أي مهارة جديدة: ببطء في البداية، ثم دفعة واحدة.",
            ],
            "takeaway": [
                "إن كان عليك أن تتذكر شيئاً واحداً عن {topic}، فليكن هذا: ابدأ صغيراً وحافظ على الاستمرارية.",
                "الخلاصة الأساسية أن {topic} يكافئ الصبر أكثر بكثير مما يكافئ الحماس المؤقت.",
            ],
            "close": [
                "هذا كل ما لدينا اليوم. شكراً لاستماعكم، ونلقاكم في الحلقة القادمة عن {topic}.",
                "نصل إلى هنا. شكراً لمشاركتنا هذا الحوار حول {topic}.",
            ],
        },
    },
    "fr": {
        "label": "French",
        "host": "fr-FR-DeniseNeural",
        "guest": "fr-FR-HenriNeural",
        "wps": 2.5,
        "t": {
            "open": [
                "Bienvenue dans ce nouvel épisode. Aujourd'hui, nous parlons de {topic}.",
                "Bonjour à toutes et à tous. Notre sujet du jour est {topic}.",
            ],
            "intro": [
                "Je reçois aujourd'hui un spécialiste qui connaît très bien {topic}.",
                "Nous accueillons une invitée qui travaille depuis des années sur {topic}.",
            ],
            "hello": [
                "Merci de m'accueillir. Je suis ravi que nous abordions enfin {topic}.",
                "Ravi d'être ici. Le sujet de {topic} me tient beaucoup à cœur.",
            ],
            "ask": [
                "Commençons simplement : qu'est-ce que {topic}, exactement ?",
                "Comment expliqueriez-vous {topic} à quelqu'un qui en entend parler pour la première fois ?",
                "Pourquoi {topic} est-il important aujourd'hui ?",
                "Quelle est la plus grande idée reçue au sujet de {topic} ?",
            ],
            "answer": [
                "Dans son principe, {topic} repose sur quelques idées simples que l'on complique souvent.",
                "La réponse courte est que {topic} influence notre quotidien bien plus qu'on ne le pense.",
                "Je dirais que {topic} se comprend mieux en observant son fonctionnement concret.",
            ],
            "react": [
                "C'est une façon très claire de présenter les choses.",
                "Cela fait beaucoup de sens, surtout à propos de {topic}.",
                "Intéressant, je n'avais jamais envisagé {topic} sous cet angle.",
            ],
            "example": [
                "Par exemple, lorsqu'on découvre {topic}, on remarque généralement un changement en quelques semaines.",
                "Prenons le cas d'une petite équipe qui a pris {topic} au sérieux et réorganisé sa routine.",
                "Considérez {topic} comme l'apprentissage d'une nouvelle compétence : lentement d'abord, puis d'un coup.",
            ],
            "takeaway": [
                "Si vous devez retenir une seule chose sur {topic}, retenez ceci : commencez petit et restez régulier.",
                "L'essentiel à retenir est que {topic} récompense la patience plus que l'intensité.",
            ],
            "close": [
                "C'est tout pour aujourd'hui. Merci de votre écoute et à bientôt pour un nouvel épisode sur {topic}.",
                "Nous en resterons là. Merci de nous avoir suivis pour cette conversation sur {topic}.",
            ],
        },
    },
    "es": {
        "label": "Spanish",
        "host": "es-ES-ElviraNeural",
        "guest": "es-ES-AlvaroNeural",
        "wps": 2.6,
        "t": {
            "open": [
                "Bienvenidos a un nuevo episodio. Hoy hablamos de {topic}.",
                "Hola a todos, gracias por acompañarnos. Nuestro tema de hoy es {topic}.",
            ],
            "intro": [
                "Nos acompaña hoy un especialista que conoce muy bien {topic}.",
                "Con nosotros está una invitada que lleva años trabajando en {topic}.",
            ],
            "hello": [
                "Gracias por invitarme. Me alegra que por fin hablemos de {topic}.",
                "Encantado de estar aquí. El tema de {topic} me apasiona.",
            ],
            "ask": [
                "Empecemos por lo básico: ¿qué es exactamente {topic}?",
                "¿Cómo explicaría {topic} a alguien que lo escucha por primera vez?",
                "¿Por qué {topic} es importante ahora mismo?",
                "¿Cuál es el mayor malentendido sobre {topic}?",
            ],
            "answer": [
                "En esencia, {topic} se reduce a unas pocas ideas sencillas que a menudo complicamos.",
                "La respuesta corta es que {topic} influye en nuestra vida diaria mucho más de lo que creemos.",
                "Diría que {topic} se entiende mejor observando cómo funciona en la práctica.",
            ],
            "react": [
                "Es una forma muy clara de plantearlo.",
                "Tiene mucho sentido, sobre todo tratándose de {topic}.",
                "Interesante, nunca había pensado en {topic} desde ese punto de vista.",
            ],
            "example": [
                "Por ejemplo, cuando alguien descubre {topic}, suele notar el cambio en pocas semanas.",
                "Piense en un equipo pequeño que se tomó {topic} en serio y reorganizó toda su rutina.",
                "Trate {topic} como el aprendizaje de cualquier habilidad nueva: despacio al principio, y luego de golpe.",
            ],
            "takeaway": [
                "Si debe recordar una sola cosa sobre {topic}, que sea esta: empiece pequeño y sea constante.",
                "La conclusión principal es que {topic} premia la paciencia mucho más que la intensidad.",
            ],
            "close": [
                "Y con esto nos despedimos. Gracias por escucharnos y hasta el próximo episodio sobre {topic}.",
                "Lo dejamos aquí. Gracias por acompañarnos en esta conversación sobre {topic}.",
            ],
        },
    },
    "de": {
        "label": "German",
        "host": "de-DE-KatjaNeural",
        "guest": "de-DE-ConradNeural",
        "wps": 2.4,
        "t": {
            "open": [
                "Willkommen zu einer neuen Folge. Heute sprechen wir über {topic}.",
                "Hallo und schön, dass Sie dabei sind. Unser Thema heute ist {topic}.",
            ],
            "intro": [
                "Bei mir im Studio ist heute ein Gast, der seit Jahren zu {topic} arbeitet.",
                "Uns begleitet heute eine Spezialistin, die {topic} sehr gut kennt.",
            ],
            "hello": [
                "Danke für die Einladung. Ich freue mich, dass wir endlich über {topic} sprechen.",
                "Gern geschehen. Das Thema {topic} liegt mir sehr am Herzen.",
            ],
            "ask": [
                "Fangen wir einfach an: Was genau ist {topic}?",
                "Wie würden Sie {topic} jemandem erklären, der zum ersten Mal davon hört?",
                "Warum ist {topic} gerade jetzt wichtig?",
                "Was ist das größte Missverständnis über {topic}?",
            ],
            "answer": [
                "Im Kern geht es bei {topic} um einige einfache Ideen, die wir oft zu kompliziert machen.",
                "Die kurze Antwort lautet: {topic} beeinflusst unseren Alltag viel stärker, als die meisten denken.",
                "Ich würde sagen, {topic} versteht man am besten, wenn man betrachtet, wie es praktisch funktioniert.",
            ],
            "react": [
                "Das ist eine sehr hilfreiche Art, es auszudrücken.",
                "Das leuchtet ein, gerade mit Blick auf {topic}.",
                "Interessant, so habe ich {topic} noch nicht betrachtet.",
            ],
            "example": [
                "Wenn Menschen zum Beispiel erstmals mit {topic} in Berührung kommen, merken sie oft schon nach wenigen Wochen einen Unterschied.",
                "Nehmen wir ein kleines Team, das {topic} ernst genommen und seine Routine komplett umgestellt hat.",
                "Betrachten Sie {topic} wie das Lernen einer neuen Fähigkeit: erst langsam, dann auf einmal.",
            ],
            "takeaway": [
                "Wenn Sie eines zu {topic} mitnehmen, dann dies: fangen Sie klein an und bleiben Sie dran.",
                "Die wichtigste Erkenntnis ist: {topic} belohnt Geduld weit mehr als Intensität.",
            ],
            "close": [
                "Das war es für heute. Danke fürs Zuhören und bis zur nächsten Folge über {topic}.",
                "Wir belassen es dabei. Danke für dieses Gespräch über {topic}.",
            ],
        },
    },
    "it": {
        "label": "Italian",
        "host": "it-IT-ElsaNeural",
        "guest": "it-IT-DiegoNeural",
        "wps": 2.6,
        "t": {
            "open": [
                "Benvenuti a una nuova puntata. Oggi parliamo di {topic}.",
                "Ciao a tutti, grazie per essere con noi. Il tema di oggi è {topic}.",
            ],
            "intro": [
                "Oggi è con noi un ospite che conosce molto bene {topic}.",
                "Ci accompagna una specialista che lavora da anni su {topic}.",
            ],
            "hello": [
                "Grazie per l'invito. Sono felice che finalmente parliamo di {topic}.",
                "È un piacere essere qui. Il tema di {topic} mi sta molto a cuore.",
            ],
            "ask": [
                "Iniziamo dalle basi: che cos'è esattamente {topic}?",
                "Come spiegherebbe {topic} a qualcuno che ne sente parlare per la prima volta?",
                "Perché {topic} è importante proprio adesso?",
                "Qual è il malinteso più grande su {topic}?",
            ],
            "answer": [
                "In sostanza, {topic} si riduce a poche idee semplici che spesso complichiamo.",
                "La risposta breve è che {topic} influenza la nostra quotidianità molto più di quanto pensiamo.",
                "Direi che {topic} si capisce meglio osservando come funziona nella pratica.",
            ],
            "react": [
                "È un modo molto chiaro di presentarlo.",
                "Ha molto senso, soprattutto parlando di {topic}.",
                "Interessante, non avevo mai pensato a {topic} da questa prospettiva.",
            ],
            "example": [
                "Per esempio, quando le persone incontrano {topic} per la prima volta, notano spesso un cambiamento in poche settimane.",
                "Pensiamo a un piccolo team che ha preso {topic} sul serio e ha riorganizzato la sua routine.",
                "Consideri {topic} come l'apprendimento di una nuova abilità: piano all'inizio, poi tutto insieme.",
            ],
            "takeaway": [
                "Se deve ricordare una sola cosa su {topic}, sia questa: inizi in piccolo e resti costante.",
                "La conclusione principale è che {topic} premia la pazienza molto più dell'intensità.",
            ],
            "close": [
                "È tutto per oggi. Grazie per l'ascolto e arrivederci alla prossima puntata su {topic}.",
                "Ci fermiamo qui. Grazie per averci seguito in questa conversazione su {topic}.",
            ],
        },
    },
    "pt": {
        "label": "Portuguese",
        "host": "pt-BR-FranciscaNeural",
        "guest": "pt-BR-AntonioNeural",
        "wps": 2.6,
        "t": {
            "open": [
                "Bem-vindos a mais um episódio. Hoje vamos falar sobre {topic}.",
                "Olá a todos, obrigado por nos acompanhar. O tema de hoje é {topic}.",
            ],
            "intro": [
                "Hoje nos acompanha um convidado que conhece muito bem {topic}.",
                "Está connosco uma especialista que trabalha há anos com {topic}.",
            ],
            "hello": [
                "Obrigado pelo convite. Fico feliz que finalmente vamos falar de {topic}.",
                "É um prazer estar aqui. O tema {topic} é muito importante para mim.",
            ],
            "ask": [
                "Vamos começar pelo básico: o que é exatamente {topic}?",
                "Como explicaria {topic} a alguém que ouve falar nisso pela primeira vez?",
                "Por que {topic} é importante agora?",
                "Qual é o maior mal-entendido sobre {topic}?",
            ],
            "answer": [
                "No fundo, {topic} se resume a algumas ideias simples que costumamos complicar.",
                "A resposta curta é que {topic} influencia o nosso dia a dia muito mais do que se imagina.",
                "Eu diria que {topic} se entende melhor observando como funciona na prática.",
            ],
            "react": [
                "É uma forma muito clara de colocar a questão.",
                "Faz todo o sentido, principalmente falando de {topic}.",
                "Interessante, nunca tinha pensado em {topic} por esse ângulo.",
            ],
            "example": [
                "Por exemplo, quando as pessoas conhecem {topic}, costumam notar uma mudança em poucas semanas.",
                "Pense numa equipa pequena que levou {topic} a sério e reorganizou toda a sua rotina.",
                "Encare {topic} como aprender uma nova habilidade: devagar no início, e depois tudo de uma vez.",
            ],
            "takeaway": [
                "Se você deve lembrar de uma coisa sobre {topic}, que seja esta: comece pequeno e seja consistente.",
                "A principal conclusão é que {topic} recompensa a paciência muito mais do que a intensidade.",
            ],
            "close": [
                "É tudo por hoje. Obrigado por nos ouvir e até ao próximo episódio sobre {topic}.",
                "Ficamos por aqui. Obrigado por acompanhar esta conversa sobre {topic}.",
            ],
        },
    },
    "tr": {
        "label": "Turkish",
        "host": "tr-TR-EmelNeural",
        "guest": "tr-TR-AhmetNeural",
        "wps": 2.4,
        "t": {
            "open": [
                "Yeni bir bölüme hoş geldiniz. Bugün {topic} konusunu konuşuyoruz.",
                "Herkese merhaba, bize katıldığınız için teşekkürler. Bugünkü konumuz {topic}.",
            ],
            "intro": [
                "Stüdyoda bugün {topic} üzerine yıllardır çalışan bir konuğumuz var.",
                "Bugün bize {topic} konusunu çok iyi bilen bir uzman katılıyor.",
            ],
            "hello": [
                "Davet için teşekkürler. Sonunda {topic} hakkında konuştuğumuz için memnunum.",
                "Burada olmaktan mutluyum. {topic} benim için çok önemli bir konu.",
            ],
            "ask": [
                "Basit bir yerden başlayalım: {topic} tam olarak nedir?",
                "{topic} konusunu ilk kez duyan birine nasıl anlatırsınız?",
                "Neden {topic} şu anda önemli?",
                "{topic} hakkındaki en büyük yanlış anlama nedir?",
            ],
            "answer": [
                "Özünde {topic}, genellikle gereğinden fazla karmaşıklaştırdığımız birkaç basit fikre dayanır.",
                "Kısa cevap şu: {topic} günlük hayatımızı çoğu insanın düşündüğünden çok daha fazla etkiler.",
                "Bence {topic} en iyi şekilde pratikte nasıl çalıştığına bakılarak anlaşılır.",
            ],
            "react": [
                "Bunu ifade etmenin gerçekten açık bir yolu.",
                "Bu çok mantıklı, özellikle {topic} söz konusuyken.",
                "İlginç, {topic} konusunu daha önce bu açıdan düşünmemiştim.",
            ],
            "example": [
                "Örneğin insanlar {topic} ile ilk kez karşılaştıklarında, değişimi genellikle birkaç hafta içinde fark ederler.",
                "Küçük bir ekibin {topic} konusunu ciddiye alıp tüm rutinini yeniden kurduğunu düşünün.",
                "{topic} konusunu yeni bir beceri öğrenmek gibi düşünün: önce yavaş, sonra birdenbire.",
            ],
            "takeaway": [
                "{topic} hakkında tek bir şey hatırlayacaksanız, bu olsun: küçük başlayın ve istikrarlı olun.",
                "Ana sonuç şu: {topic} yoğunluktan çok sabrı ödüllendirir.",
            ],
            "close": [
                "Bugün bu kadar. Dinlediğiniz için teşekkürler, {topic} konulu bir sonraki bölümde görüşmek üzere.",
                "Burada bırakıyoruz. {topic} üzerine bu sohbete katıldığınız için teşekkürler.",
            ],
        },
    },
    "ru": {
        "label": "Russian",
        "host": "ru-RU-SvetlanaNeural",
        "guest": "ru-RU-DmitryNeural",
        "wps": 2.4,
        "t": {
            "open": [
                "Добро пожаловать в новый выпуск. Сегодня мы говорим о теме {topic}.",
                "Здравствуйте и спасибо, что вы с нами. Наша сегодняшняя тема — {topic}.",
            ],
            "intro": [
                "В студии сегодня гость, который много лет работает с темой {topic}.",
                "С нами специалист, который очень хорошо знает {topic}.",
            ],
            "hello": [
                "Спасибо за приглашение. Я рад, что мы наконец говорим о {topic}.",
                "Рад быть здесь. Тема {topic} для меня очень важна.",
            ],
            "ask": [
                "Начнём с простого: что такое {topic} на самом деле?",
                "Как бы вы объяснили {topic} тому, кто слышит об этом впервые?",
                "Почему {topic} важно именно сейчас?",
                "Какое самое большое заблуждение о {topic}?",
            ],
            "answer": [
                "По сути, {topic} сводится к нескольким простым идеям, которые мы часто усложняем.",
                "Короткий ответ: {topic} влияет на нашу повседневную жизнь гораздо сильнее, чем кажется.",
                "Я бы сказал, что {topic} лучше всего понимать, глядя на то, как это работает на практике.",
            ],
            "react": [
                "Это очень понятный способ объяснить.",
                "Это вполне логично, особенно когда речь о {topic}.",
                "Интересно, я раньше не думал о {topic} с этой стороны.",
            ],
            "example": [
                "Например, когда люди впервые сталкиваются с {topic}, они обычно замечают изменения уже через несколько недель.",
                "Представьте небольшую команду, которая отнеслась к {topic} серьёзно и полностью перестроила свой распорядок.",
                "Относитесь к {topic} как к освоению любого нового навыка: сначала медленно, а потом сразу.",
            ],
            "takeaway": [
                "Если вы запомните об {topic} только одну вещь, пусть это будет такая: начните с малого и будьте постоянны.",
                "Главный вывод: {topic} вознаграждает терпение гораздо больше, чем интенсивность.",
            ],
            "close": [
                "На сегодня всё. Спасибо, что слушали, и до встречи в следующем выпуске о {topic}.",
                "На этом мы остановимся. Спасибо за эту беседу о {topic}.",
            ],
        },
    },
    "zh": {
        "label": "Chinese",
        "host": "zh-CN-XiaoxiaoNeural",
        "guest": "zh-CN-YunjianNeural",
        "wps": 4.2,
        "t": {
            "open": [
                "欢迎收听新一期的节目。今天我们来聊聊{topic}。",
                "大家好，感谢收听。我们今天的主题是{topic}。",
            ],
            "intro": [
                "今天来到直播间的是一位在{topic}领域工作多年的嘉宾。",
                "我们邀请到一位非常了解{topic}的专家。",
            ],
            "hello": [
                "谢谢邀请。很高兴我们终于聊到{topic}。",
                "很高兴来到这里。{topic}是我非常关注的主题。",
            ],
            "ask": [
                "我们先从最简单的开始：{topic}到底是什么？",
                "如果有人第一次听说{topic}，你会怎么解释？",
                "为什么{topic}现在很重要？",
                "关于{topic}，人们最大的误解是什么？",
            ],
            "answer": [
                "本质上，{topic}其实只涉及几个简单的概念，只是我们常常把它想复杂了。",
                "简单来说，{topic}对我们日常生活的影响远超大多数人的想象。",
                "我认为，理解{topic}最好的方式是看它在实际中如何运作。",
            ],
            "react": [
                "这个说法非常清楚。",
                "很有道理，特别是在{topic}这个问题上。",
                "很有意思，我之前没有从这个角度想过{topic}。",
            ],
            "example": [
                "举个例子，当人们第一次接触{topic}时，通常在几周内就会感受到变化。",
                "可以想象一个小团队认真对待{topic}，并围绕它重建了整个流程。",
                "把{topic}当成学习一项新技能：开始很慢，然后突然就通了。",
            ],
            "takeaway": [
                "如果关于{topic}你只记住一件事，那就是：从小处开始，并坚持下去。",
                "最重要的结论是：{topic}奖励的是耐心，而不是一时的强度。",
            ],
            "close": [
                "今天的节目就到这里。感谢收听，下一期我们再聊{topic}。",
                "我们就聊到这里。感谢你收听这期关于{topic}的对话。",
            ],
        },
    },
    "ja": {
        "label": "Japanese",
        "host": "ja-JP-NanamiNeural",
        "guest": "ja-JP-KeitaNeural",
        "wps": 4.4,
        "t": {
            "open": [
                "新しいエピソードへようこそ。今日は{topic}についてお話しします。",
                "皆さんこんにちは、お聴きいただきありがとうございます。今日のテーマは{topic}です。",
            ],
            "intro": [
                "本日のスタジオには、長年{topic}に取り組んできたゲストをお迎えしています。",
                "今日は{topic}をよく知る専門家に来ていただいています。",
            ],
            "hello": [
                "お招きいただきありがとうございます。ようやく{topic}についてお話しできて嬉しいです。",
                "ここに来られて嬉しいです。{topic}は私が大切にしているテーマです。",
            ],
            "ask": [
                "まずはシンプルな質問から。{topic}とは一体何でしょうか？",
                "初めて{topic}を耳にする人に、どのように説明しますか？",
                "なぜ今{topic}が重要なのでしょうか？",
                "{topic}について最も大きな誤解は何ですか？",
            ],
            "answer": [
                "本質的に{topic}は、私たちが複雑にしがちな、いくつかのシンプルな考えに集約されます。",
                "端的に言えば、{topic}は多くの人が思うよりもずっと私たちの日常に影響しています。",
                "{topic}は、実際にどのように機能するかを見ることで最もよく理解できると思います。",
            ],
            "react": [
                "とても分かりやすい説明の仕方ですね。",
                "とても納得できます、特に{topic}については。",
                "興味深いです。{topic}をその角度から考えたことはありませんでした。",
            ],
            "example": [
                "例えば、人が初めて{topic}に触れると、通常は数週間で変化に気づきます。",
                "小さなチームが{topic}を真剣に受け止め、日常のやり方を作り直した例を思い浮かべてください。",
                "{topic}は新しい技能を学ぶようなものだと考えてください。最初はゆっくり、そして一気に進みます。",
            ],
            "takeaway": [
                "{topic}について一つだけ覚えるなら、こうです。小さく始めて、続けること。",
                "最も大切な結論は、{topic}は強度よりも忍耐に報いるということです。",
            ],
            "close": [
                "今日はここまでです。お聴きいただきありがとうございました。また次回、{topic}についてお話しします。",
                "ここまでにしましょう。{topic}についての対談にお付き合いいただきありがとうございました。",
            ],
        },
    },
    "ko": {
        "label": "Korean",
        "host": "ko-KR-SunHiNeural",
        "guest": "ko-KR-InJoonNeural",
        "wps": 3.6,
        "t": {
            "open": [
                "새 에피소드에 오신 것을 환영합니다. 오늘은 {topic}에 대해 이야기합니다.",
                "여러분 반갑습니다, 함께해 주셔서 감사합니다. 오늘의 주제는 {topic}입니다.",
            ],
            "intro": [
                "오늘 스튜디오에는 오랫동안 {topic}을 연구해 온 분이 함께합니다.",
                "오늘은 {topic}을 잘 아는 전문가를 모셨습니다.",
            ],
            "hello": [
                "초대해 주셔서 감사합니다. 드디어 {topic}에 대해 이야기하게 되어 기쁩니다.",
                "이 자리에 오게 되어 기쁩니다. {topic}은 제가 매우 중요하게 생각하는 주제입니다.",
            ],
            "ask": [
                "간단한 것부터 시작하죠. {topic}이란 정확히 무엇인가요?",
                "{topic}을 처음 듣는 사람에게 어떻게 설명하시겠습니까?",
                "왜 지금 {topic}이 중요한가요?",
                "{topic}에 대한 가장 큰 오해는 무엇인가요?",
            ],
            "answer": [
                "본질적으로 {topic}은 우리가 흔히 복잡하게 만드는 몇 가지 단순한 개념으로 정리됩니다.",
                "짧게 말하면, {topic}은 대부분의 사람이 생각하는 것보다 일상에 훨씬 큰 영향을 미칩니다.",
                "{topic}은 실제로 어떻게 작동하는지 보면 가장 잘 이해할 수 있다고 생각합니다.",
            ],
            "react": [
                "정말 명확한 설명 방식이네요.",
                "매우 일리가 있습니다, 특히 {topic}에 관해서는요.",
                "흥미롭네요, {topic}을 그런 관점에서 생각해 본 적은 없었습니다.",
            ],
            "example": [
                "예를 들어, 사람들이 처음 {topic}을 접하면 보통 몇 주 안에 변화를 느낍니다.",
                "작은 팀이 {topic}을 진지하게 받아들이고 일상을 완전히 다시 구성한 경우를 생각해 보세요.",
                "{topic}은 새로운 기술을 배우는 것처럼 생각하세요. 처음에는 천천히, 그리고 한꺼번에 옵니다.",
            ],
            "takeaway": [
                "{topic}에 대해 한 가지만 기억한다면, 그것은 이것입니다. 작게 시작하고 꾸준히 하세요.",
                "가장 중요한 결론은 {topic}은 강도보다 인내에 보상한다는 것입니다.",
            ],
            "close": [
                "오늘은 여기까지입니다. 들어주셔서 감사합니다, 다음에 {topic}으로 다시 만나요.",
                "여기서 마무리하죠. {topic}에 대한 대화에 함께해 주셔서 감사합니다.",
            ],
        },
    },
    "hi": {
        "label": "Hindi",
        "host": "hi-IN-SwaraNeural",
        "guest": "hi-IN-MadhurNeural",
        "wps": 2.4,
        "t": {
            "open": [
                "नए एपिसोड में आपका स्वागत है। आज हम {topic} के बारे में बात करेंगे।",
                "नमस्कार, साथ देने के लिए धन्यवाद। आज का विषय है {topic}।",
            ],
            "intro": [
                "आज स्टूडियो में हमारे साथ एक मेहमान हैं जो वर्षों से {topic} पर काम कर रहे हैं।",
                "आज हमारे साथ एक विशेषज्ञ हैं जो {topic} को बहुत अच्छी तरह जानते हैं।",
            ],
            "hello": [
                "आमंत्रित करने के लिए धन्यवाद। खुशी है कि आज हम {topic} पर बात कर रहे हैं।",
                "यहाँ आकर अच्छा लगा। {topic} मेरे लिए बहुत महत्वपूर्ण विषय है।",
            ],
            "ask": [
                "शुरू करते हैं एक साधारण सवाल से: {topic} है आखिर क्या?",
                "अगर कोई पहली बार {topic} के बारे में सुने, तो आप उसे कैसे समझाएंगे?",
                "{topic} अभी क्यों महत्वपूर्ण है?",
                "{topic} के बारे में सबसे बड़ी गलतफहमी क्या है?",
            ],
            "answer": [
                "मूल रूप से {topic} कुछ सरल विचारों पर आधारित है, जिन्हें हम अक्सर ज़रूरत से ज़्यादा जटिल बना देते हैं।",
                "संक्षेप में, {topic} हमारे दैनिक जीवन पर हमारी सोच से कहीं अधिक प्रभाव डालता है।",
                "मेरे अनुसार {topic} को समझने का सबसे अच्छा तरीका है यह देखना कि यह व्यावहारिक रूप से कैसे काम करता है।",
            ],
            "react": [
                "यह समझाने का बहुत स्पष्ट तरीका है।",
                "यह बहुत तर्कसंगत है, खासकर {topic} के संदर्भ में।",
                "दिलचस्प है, मैंने {topic} के बारे में इस नज़रिए से कभी नहीं सोचा।",
            ],
            "example": [
                "उदाहरण के लिए, जब लोग पहली बार {topic} से मिलते हैं, तो आम तौर पर कुछ हफ़्तों में उन्हें बदलाव दिखता है।",
                "सोचिए एक छोटी टीम ने {topic} को गंभीरता से लिया और अपनी पूरी दिनचर्या बदल दी।",
                "{topic} को एक नई कला सीखने जैसा समझिए: पहले धीरे-धीरे, फिर एक साथ।",
            ],
            "takeaway": [
                "अगर आपको {topic} के बारे में एक बात याद रखनी हो, तो वह यह है: छोटी शुरुआत करें और लगातार बने रहें।",
                "मुख्य निष्कर्ष यह है कि {topic} तीव्रता से अधिक धैर्य को पुरस्कृत करता है।",
            ],
            "close": [
                "आज के लिए इतना ही। सुनने के लिए धन्यवाद, अगले एपिसोड में {topic} पर फिर मिलेंगे।",
                "यहीं समाप्त करते हैं। {topic} पर इस बातचीत में साथ देने के लिए धन्यवाद।",
            ],
        },
    },
    "id": {
        "label": "Indonesian",
        "host": "id-ID-GadisNeural",
        "guest": "id-ID-ArdiNeural",
        "wps": 2.5,
        "t": {
            "open": [
                "Selamat datang di episode baru. Hari ini kita membahas {topic}.",
                "Halo semua, terima kasih sudah bergabung. Topik kita hari ini adalah {topic}.",
            ],
            "intro": [
                "Bersama kita hari ini ada tamu yang sudah bertahun-tahun berkecimpung di {topic}.",
                "Kita didampingi seorang ahli yang sangat memahami {topic}.",
            ],
            "hello": [
                "Terima kasih atas undangannya. Senang akhirnya kita membahas {topic}.",
                "Senang berada di sini. {topic} adalah topik yang sangat saya pedulikan.",
            ],
            "ask": [
                "Mari mulai dari yang sederhana: apa sebenarnya {topic} itu?",
                "Bagaimana Anda menjelaskan {topic} kepada seseorang yang baru pertama kali mendengarnya?",
                "Mengapa {topic} penting saat ini?",
                "Apa kesalahpahaman terbesar tentang {topic}?",
            ],
            "answer": [
                "Pada dasarnya, {topic} bermuara pada beberapa gagasan sederhana yang sering kita buat rumit.",
                "Jawabannya singkat: {topic} memengaruhi keseharian kita jauh lebih besar daripada yang kita kira.",
                "Menurut saya, {topic} paling mudah dipahami dengan melihat cara kerjanya di praktik.",
            ],
            "react": [
                "Itu cara yang sangat jelas untuk menjelaskannya.",
                "Itu sangat masuk akal, terutama soal {topic}.",
                "Menarik, saya belum pernah memikirkan {topic} dari sudut itu.",
            ],
            "example": [
                "Misalnya, saat orang pertama kali mengenal {topic}, biasanya mereka melihat perubahan dalam beberapa minggu.",
                "Bayangkan sebuah tim kecil yang menanggapi {topic} secara serius dan menata ulang rutinitasnya.",
                "Anggap {topic} seperti mempelajari keterampilan baru: pelan di awal, lalu sekaligus.",
            ],
            "takeaway": [
                "Jika Anda hanya mengingat satu hal tentang {topic}, ingatlah ini: mulailah dari yang kecil dan konsistenlah.",
                "Kesimpulan utamanya: {topic} lebih menghargai kesabaran daripada intensitas.",
            ],
            "close": [
                "Sekian untuk hari ini. Terima kasih sudah mendengarkan, sampai jumpa di episode berikutnya tentang {topic}.",
                "Kita akhiri di sini. Terima kasih telah mengikuti percakapan tentang {topic}.",
            ],
        },
    },
    "ur": {
        "label": "Urdu",
        "host": "ur-PK-UzmaNeural",
        "guest": "ur-PK-AsadNeural",
        "wps": 2.3,
        "t": {
            "open": [
                "نئی قسط میں خوش آمدید۔ آج ہم {topic} کے بارے میں بات کریں گے۔",
                "سب کو سلام، ساتھ دینے کا شکریہ۔ آج کا موضوع {topic} ہے۔",
            ],
            "intro": [
                "آج اسٹوڈیو میں ہمارے ساتھ ایک مہمان ہیں جو برسوں سے {topic} پر کام کر رہے ہیں۔",
                "آج ہمارے ساتھ ایک ماہر ہیں جو {topic} کو بہت اچھی طرح جانتے ہیں۔",
            ],
            "hello": [
                "مدعو کرنے کا شکریہ۔ خوشی ہے کہ آج ہم {topic} پر بات کر رہے ہیں۔",
                "یہاں آکر اچھا لگا۔ {topic} میرے لیے بہت اہم موضوع ہے۔",
            ],
            "ask": [
                "آئیے ایک سادہ سوال سے شروع کرتے ہیں: {topic} ہے آخر کیا؟",
                "اگر کوئی پہلی بار {topic} کے بارے میں سنے، تو آپ اسے کیسے سمجھائیں گے؟",
                "{topic} اب کیوں اہم ہے؟",
                "{topic} کے بارے میں سب سے بڑی غلط فہمی کیا ہے؟",
            ],
            "answer": [
                "بنیادی طور پر {topic} چند سادہ خیالات پر مبنی ہے جنہیں ہم اکثر ضرورت سے زیادہ پیچیدہ بنا دیتے ہیں۔",
                "مختصر جواب یہ ہے کہ {topic} ہماری روزمرہ زندگی پر ہماری سوچ سے کہیں زیادہ اثر ڈالتا ہے۔",
                "میرے خیال میں {topic} کو سمجھنے کا بہترین طریقہ یہ ہے کہ دیکھا جائے کہ یہ عملی طور پر کیسے کام کرتا ہے۔",
            ],
            "react": [
                "یہ سمجھانے کا بہت واضح انداز ہے۔",
                "یہ بہت معقول بات ہے، خاص طور پر {topic} کے حوالے سے۔",
                "دلچسپ ہے، میں نے {topic} کے بارے میں اس زاویے سے کبھی نہیں سوچا۔",
            ],
            "example": [
                "مثال کے طور پر، جب لوگ پہلی بار {topic} سے واقف ہوتے ہیں تو عموماً چند ہفتوں میں انہیں فرق نظر آتا ہے۔",
                "ایک چھوٹی ٹیم کا تصور کریں جس نے {topic} کو سنجیدگی سے لیا اور اپنا پورا معمول بدل دیا۔",
                "{topic} کو ایک نئی مہارت سیکھنے جیسا سمجھیں: پہلے آہستہ، پھر ایک ساتھ۔",
            ],
            "takeaway": [
                "اگر آپ کو {topic} کے بارے میں ایک بات یاد رکھنی ہو تو وہ یہ ہے: چھوٹا آغاز کریں اور تسلسل برقرار رکھیں۔",
                "اصل نتیجہ یہ ہے کہ {topic} شدت سے زیادہ صبر کا صلہ دیتا ہے۔",
            ],
            "close": [
                "آج کے لیے اتنا ہی۔ سننے کا شکریہ، اگلی قسط میں {topic} پر پھر ملیں گے۔",
                "یہیں ختم کرتے ہیں۔ {topic} پر اس گفتگو میں ساتھ دینے کا شکریہ۔",
            ],
        },
    },
    "fa": {
        "label": "Persian",
        "host": "fa-IR-DilaraNeural",
        "guest": "fa-IR-FaridNeural",
        "wps": 2.4,
        "t": {
            "open": [
                "به قسمت جدید خوش آمدید. امروز درباره {topic} صحبت می‌کنیم.",
                "سلام به همه، ممنون که همراه ما هستید. موضوع امروز ما {topic} است.",
            ],
            "intro": [
                "امروز در استودیو مهمانی داریم که سال‌ها روی {topic} کار کرده است.",
                "یک متخصص که {topic} را بسیار خوب می‌شناسد همراه ماست.",
            ],
            "hello": [
                "ممنون از دعوت. خوشحالم که بالاخره درباره {topic} صحبت می‌کنیم.",
                "خوشحالم اینجا هستم. {topic} موضوع بسیار مهمی برای من است.",
            ],
            "ask": [
                "بیایید از یک پرسش ساده شروع کنیم: {topic} دقیقاً چیست؟",
                "چگونه {topic} را برای کسی که برای اولین بار می‌شنود توضیح می‌دهید؟",
                "چرا {topic} امروز اهمیت دارد؟",
                "بزرگ‌ترین سوءتفاهم درباره {topic} چیست؟",
            ],
            "answer": [
                "در اصل، {topic} به چند ایده ساده برمی‌گردد که ما اغلب آن‌ها را پیچیده می‌کنیم.",
                "پاسخ کوتاه این است که {topic} بر زندگی روزمره ما بسیار بیشتر از آنچه فکر می‌کنیم اثر می‌گذارد.",
                "به نظرم {topic} را بهتر است با دیدن نحوه عمل آن در عمل درک کرد.",
            ],
            "react": [
                "این روش بسیار روشنی برای توضیح است.",
                "کاملاً منطقی است، به‌ویژه درباره {topic}.",
                "جالب است، من قبلاً از این زاویه به {topic} فکر نکرده بودم.",
            ],
            "example": [
                "برای مثال، وقتی افراد برای اولین بار با {topic} روبه‌رو می‌شوند، معمولاً طی چند هفته تغییر را احساس می‌کنند.",
                "تیم کوچکی را تصور کنید که {topic} را جدی گرفت و کل روال خود را بازسازی کرد.",
                "{topic} را مانند یادگیری یک مهارت جدید در نظر بگیرید: ابتدا آهسته، سپس یک‌باره.",
            ],
            "takeaway": [
                "اگر قرار است یک چیز درباره {topic} به یاد داشته باشید، این باشد: کوچک شروع کنید و پیوسته ادامه دهید.",
                "نتیجه اصلی این است که {topic} بیش از شدت، به شکیبایی پاداش می‌دهد.",
            ],
            "close": [
                "برای امروز کافی است. ممنون که شنیدید، در قسمت بعدی درباره {topic} دوباره می‌بینیمتان.",
                "همین‌جا تمام می‌کنیم. ممنون که در این گفتگو درباره {topic} همراه ما بودید.",
            ],
        },
    },
}


def supported_languages() -> list[dict[str, str]]:
    """Return the languages the owner can choose from, for the Cockpit UI."""
    return [
        {"code": code, "label": pack["label"], "host": pack["host"], "guest": pack["guest"]}
        for code, pack in LANGUAGE_PACKS.items()
    ]


# Pickable voices per language for the cockpit Generate form. Kokoro voices
# work with the free local Docker deployment; Edge voices are free cloud;
# ElevenLabs voices need ELEVENLABS_API_KEY.
VOICE_OPTIONS: dict[str, list[dict[str, str]]] = {
    "en": [
        {"id": "af_bella", "label": "Bella — Kokoro local, warm female", "provider": "kokoro"},
        {"id": "am_adam", "label": "Adam — Kokoro local, deep male", "provider": "kokoro"},
        {"id": "af_nicole", "label": "Nicole — Kokoro local, young female", "provider": "kokoro"},
        {"id": "am_michael", "label": "Michael — Kokoro local, young male", "provider": "kokoro"},
        {"id": "en-US-AriaNeural", "label": "Aria — Edge free cloud, female", "provider": "edge_tts"},
        {"id": "en-US-GuyNeural", "label": "Guy — Edge free cloud, male", "provider": "edge_tts"},
        {"id": "21m00Tcm4TlvDq8ikWAM", "label": "Adam — ElevenLabs (needs API key)", "provider": "elevenlabs_tts"},
        {"id": "EXAVITQu4vr4xnSDxMaL", "label": "Bella — ElevenLabs (needs API key)", "provider": "elevenlabs_tts"},
    ],
    "ar": [
        {"id": "ar-SA-ZariyahNeural", "label": "Zariyah — Edge free cloud, female", "provider": "edge_tts"},
        {"id": "ar-SA-HamedNeural", "label": "Hamed — Edge free cloud, male", "provider": "edge_tts"},
    ],
}


def voice_options(language: str = "en") -> list[dict[str, str]]:
    """Return the pickable host/guest voices for a language."""
    return VOICE_OPTIONS.get(language) or VOICE_OPTIONS["en"]


def voices_for(language: str) -> tuple[str, str]:
    """Return (host_voice, guest_voice) for a language code."""
    pack = LANGUAGE_PACKS.get(language) or LANGUAGE_PACKS["en"]
    return pack["host"], pack["guest"]


def language_label(language: str) -> str:
    pack = LANGUAGE_PACKS.get(language) or LANGUAGE_PACKS["en"]
    return pack["label"]


def build_dialogue(topic: str, language: str = "en", duration_seconds: int = 600,
                   script: str | None = None) -> list[tuple[str, str]]:
    """Build an ordered list of (speaker, line) turns for a two-voice podcast.

    ``speaker`` is either "host" or "guest". If the caller supplied a script
    with [HOST]/[GUEST] markers those turns are honoured; otherwise an
    on-topic conversation is generated and sized to fill ``duration_seconds``.
    """
    pack = LANGUAGE_PACKS.get(language) or LANGUAGE_PACKS["en"]
    topic = (topic or "our topic").strip()

    if script and script.strip():
        parsed = _parse_script(script)
        if parsed:
            return _top_up(parsed, topic, pack, duration_seconds)

    return _generate_turns(topic, pack, duration_seconds)


def _target_words(pack: dict[str, Any], duration_seconds: int) -> int:
    return max(40, int(duration_seconds * pack["wps"] * 0.95))


def _top_up(turns: list[tuple[str, str]], topic: str, pack: dict[str, Any],
            duration_seconds: int) -> list[tuple[str, str]]:
    """Extend caller-supplied turns with generated on-topic turns.

    A script that is too short for the requested duration would otherwise be
    padded with silence, so the owner would receive a track that is nominally
    the right length but mostly empty.
    """
    target = _target_words(pack, duration_seconds)
    words = sum(len(text.split()) for _, text in turns)
    if words >= target:
        return turns

    t = pack["t"]
    out = list(turns)
    i = 0
    while words < target - 40:
        out.append(("host", _pick(t["ask"], i).format(topic=topic)))
        out.append(("guest", _pick(t["answer"], i + 1).format(topic=topic)))
        out.append(("host", _pick(t["react"], i + 2).format(topic=topic)))
        out.append(("guest", _pick(t["example"], i).format(topic=topic)))
        words += sum(
            len(text.split()) for _, text in out[-4:]
        )
        i += 1
    out.append(("host", _pick(t["close"], 0).format(topic=topic)))
    return out


import re as _re


_LABEL_RE = _re.compile(r"\[HOST\]|\[GUEST\]|HOST\s*:|GUEST\s*:", _re.IGNORECASE)


def _strip_speaker_label(line: str) -> tuple[str | None, str]:
    """Split a leading speaker label off a script line.

    Accepts ``[HOST]``/``[GUEST]`` markers as well as plain ``Host:``/``Guest:``
    prefixes (any capitalisation). Returns (speaker, remainder) where speaker
    is "host"/"guest"/None. Labels must be stripped because anything left in
    the text is spoken aloud by the TTS voice.
    """
    match = _LABEL_RE.match(line.strip())
    if not match:
        return None, line.strip()
    label = match.group(0).upper()
    speaker = "host" if "HOST" in label else "guest"
    return speaker, line.strip()[match.end():].strip()


def _split_line_turns(line: str, current: str) -> list[tuple[str, str]]:
    """Split one script line into (speaker, text) turns on every label.

    Handles both multi-line scripts (one label per line) and single-line
    scripts (``Host: ... Guest: ...``), so speaker names are never spoken.
    """
    turns: list[tuple[str, str]] = []
    buffer = ""
    pos = 0
    speaker = current
    for match in _LABEL_RE.finditer(line):
        chunk = line[pos:match.start()].strip()
        if chunk:
            buffer = f"{buffer} {chunk}".strip()
        if buffer:
            turns.append((speaker, buffer))
            buffer = ""
        label = match.group(0).upper()
        speaker = "host" if "HOST" in label else "guest"
        pos = match.end()
    tail = line[pos:].strip()
    if tail:
        buffer = f"{buffer} {tail}".strip()
    if buffer:
        turns.append((speaker, buffer))
    return turns


def _parse_script(script: str) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    current = "host"
    buffer: list[str] = []
    for line in script.splitlines():
        if _LABEL_RE.search(line):
            if buffer:
                turns.append((current, " ".join(buffer).strip()))
                buffer = []
            for speaker, text in _split_line_turns(line, current):
                if text:
                    turns.append((speaker, text))
                    current = speaker
        elif line.strip():
            buffer.append(line.strip())
    if buffer:
        turns.append((current, " ".join(buffer).strip()))
    return [t for t in turns if t[1]]


def _generate_turns(topic: str, pack: dict[str, Any], duration_seconds: int) -> list[tuple[str, str]]:
    t = pack["t"]
    # Aim slightly under the target so the rendered speech never has to be cut
    # mid-sentence; the engine pads the small remainder to hit the exact length.
    target_words = max(40, int(duration_seconds * pack["wps"] * 0.95))

    turns: list[tuple[str, str]] = []
    words = 0

    def add(speaker: str, text: str) -> None:
        nonlocal words
        turns.append((speaker, text))
        words += len(text.split())

    add("host", _pick(t["open"], 0).format(topic=topic))
    add("host", _pick(t["intro"], 1).format(topic=topic))
    add("guest", _pick(t["hello"], 2).format(topic=topic))

    i = 0
    while words < target_words - 40:
        add("host", _pick(t["ask"], i).format(topic=topic))
        add("guest", _pick(t["answer"], i + 1).format(topic=topic))
        add("host", _pick(t["react"], i + 2).format(topic=topic))
        add("guest", _pick(t["example"], i).format(topic=topic))
        add("guest", _pick(t["takeaway"], i + 1).format(topic=topic))
        i += 1

    add("host", _pick(t["close"], 0).format(topic=topic))
    return turns


def dialogue_to_script(turns: list[tuple[str, str]]) -> str:
    """Render turns back into a marked-up script for provenance/ledger records."""
    return "\n".join(
        f"[{'HOST' if speaker == 'host' else 'GUEST'}]: {text}" for speaker, text in turns
    )


# ── Single-narrator video narration ────────────────────────────────────────
# Videos are always English. Previously the narration was just the topic string,
# which was either repeated awkwardly or cut off when it did not match the
# requested runtime. These lines let the narration cover the topic for the whole
# duration without fabricating specific claims.

NARRATION_LINES: list[str] = [
    "Today we are taking a closer look at {topic}.",
    "At its core, {topic} comes down to a few simple ideas that are easy to overlook.",
    "The reason {topic} matters is that it shapes far more of our daily lives than most people notice.",
    "When people first encounter {topic}, they usually underestimate how quickly it adds up.",
    "One of the most useful ways to think about {topic} is to look at how it works in practice.",
    "A common misunderstanding about {topic} is that it takes a big effort to get started.",
    "In reality, {topic} tends to reward small and steady steps far more than dramatic ones.",
    "People who work with {topic} for years will usually tell you the same thing: consistency wins.",
    "If you are new to {topic}, the best first step is simply to learn the basic vocabulary.",
    "Another useful angle on {topic} is how it connects to the wider picture around it.",
    "It also helps to remember that {topic} did not appear overnight; it developed over a long time.",
    "There is a practical side to {topic} as well, and it is easier to act on than most people expect.",
    "Looking ahead, {topic} is likely to keep growing in importance.",
    "That brings us to the takeaway: with {topic}, start small and keep going.",
    "Thanks for watching, and we hope this helped make {topic} a little clearer.",
]


def build_narration(topic: str, duration_seconds: int, wps: float = 2.6) -> str:
    """Build a single-voice English narration sized to fill the video duration."""
    topic = (topic or "our topic").strip()
    target = max(20, int(duration_seconds * wps * 0.95))
    lines: list[str] = []
    words = 0
    i = 0
    while words < target and i < 400:
        line = NARRATION_LINES[i % len(NARRATION_LINES)].format(topic=topic)
        lines.append(line)
        words += len(line.split())
        i += 1
    return " ".join(lines)

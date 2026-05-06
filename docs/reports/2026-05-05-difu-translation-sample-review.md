# 《地府叫我小先生》翻译质量抽样复核

- 项目：`project_id=31`
- 范围：`{'type': 'chapter_range', 'start': 1, 'end': 70}`
- 每类抽样数：3
- 来源分布：{"gpt": 17, "deepseek": 15, "rewrite": 38, "other": 0}
- 缺失来源：[]

## 结论

- 这次运行已经具备三类样本池：GPT primary 17 段、DeepSeek secondary 15 段、rewrite 38 段。
- 三类样本均未发现大面积漏译或原文照抄；主要风险集中在术语/称谓风格统一、文化典故注释、DeepSeek 输出格式一致性。
- 建议后续把本报告的人工观察和 `inspect.translation_samples` 输出结合，作为每次大批量翻译后的固定 QA 步骤。

## 抽样明细

### gpt

#### 第1章 第1章 鬼节，鬼敲门

- version_id：`164`
- draft_role：`primary`
- model：`gpt_5_5_aicodelink` / `gpt-5.5`

观察：
- 整体忠实，信息没有明显缺失。
- `北国十万大山` 已译为 `the Hundred-Thousand Mountains of the North`，本段地名处理较稳定；后续需要确认全书是否都沿用同一译法。

原文节选：

```text
古老偏僻的地方，总会发生许多诡异、恐怖的事情。
　　而这些事情，就发生在华九难身边。
　　甚至华九难就是这些事情的一部分。
　　比如，他是尸生子！
　　九道沟村，坐落在北国十万大山最深处。
　　这里天寒地冻，一年四季被风雪笼罩。
　　即使到了八十年代初期，村民也过着几乎与世隔绝的生活。
　　村中大小事情，都由聋婆婆和李大爷做主。
　　聋婆婆是出马弟子。
　　我国自古就有“南茅北马”之说。
　　南茅，指的是茅山道士；
　　北马，指的是北方出马仙。
　　正统的出马弟子，家里都供奉着“四梁八柱”十二位仙家。
　　四梁指的是：胡（狐狸），黄（黄鼠狼），常（蛇）和清风。
　　清风是横死的恶鬼。
　　所谓的八柱是扫，看，串，护、通天，归地，关碍，探兵这八堂。
　　关于四梁八柱的分工，后文自有交代。
　　聋婆婆其实并不聋，娘家姓张，全名王张氏。
　　只因她的出马仙是蛇类，蛇又称作小龙，所以大家才叫她聋（龙）婆婆。
　　聋婆婆老伴儿走的早，三个儿子也因为意外夭折两个。
　　只有老三伺候在聋婆婆身边。
　　村民不管大小，一般都称呼他王三。
　　今天是农历七月十五，鬼节。
　　因此刚入夜，聋婆婆就让王三关了院门，想要早点休息。
　　毕竟人鬼殊途，相互冲撞了，对谁都不好。
　　可没等她躺下，院中忽然传来一阵急促的敲门声。
　　那声音如此巨大沉闷，与其说敲，不如说是撞。
　　王三非常不满，一边披上满是补丁的棉衣去开门，一边骂骂咧咧：
　　“来了来了，别特么敲了！”
　　“你要死了着急救命还是咋滴，大晚上的叫门！”
　　院门打开，一阵阴风扑面而来。
　　门外的人仿佛一根斜靠着的木头，咕咚一声，直挺挺的倒进院子。
　　厚厚的积雪上只留下一个人形印记。
　　“哎呀我去，不会真死了吧？！”
　　王三一边把来人从积雪里拉出来，一边对着屋内大喊：
　　“娘，你快出来看看！”
　　其实在王三开门的一瞬间，聋婆婆就心中一惊。
　　她几步跑到供奉仙家的偏房，抓起捆仙绳就往外跑。
　　这里的捆仙绳，可不是神话传说中那种法宝。
　　而是出马弟子用柳枝、自己头发、老钱（古代的铜钱）等编织而成。
　　然后用松油混合香…
```

译文节选：

```text
In ancient, remote places, many strange and terrifying things are bound to happen.

And these things happened around Hua Jiunan.

Hua Jiunan was even part of them.

For example, he was a corpse-born child!

Jiudaogou Village was situated in the deepest reaches of the Hundred-Thousand Mountains of the North.

Here, the land was frozen and bitterly cold, shrouded in wind and snow throughout the year.

Even by the early 1980s, the villagers still lived lives almost entirely cut off from the outside world.

All matters in the village, great and small, were decided by Granny Deaf and Old Master Li.

Granny Deaf was a Chuma Disciple.

Since ancient times, our country has had the saying “Mao in the South, Ma in the North.”

Southern Mao refers to Maoshan Daoist priests;

Northern Ma refers to the northern Chuma Immortals.

In the homes of orthodox Chuma Disciples, the twelve members of the imm…
```

#### 第17章 第17章 三枚勋章

- version_id：`180`
- draft_role：`primary`
- model：`gpt_5_5_aicodelink` / `gpt-5.5`

观察：
- 对政治口号和群众监督语气基本保留，叙事顺畅。
- `赵干部` 处理为 `Cadre Zhao` 可接受，但和后文 `Director Zhou` 这类职务称呼需要统一风格。

原文节选：

```text
见此情景，同来的赵姓乡镇干部不高兴了。
　　因为他觉得自己被轻视了。
　　赵干部用审视的目光上下打量李大爷：
　　“老同志干嘛要神神秘秘的？！”
　　“有事情就在这里说！”
　　“任何事情都要接受人民群众监督！”
　　“没啥见不得人的，除非......除非你和这起命案有关，人是你杀的！”
　　这话一出口，立即惹了众怒。
　　李大爷在村里的威望，比聋婆婆都要高。
　　尤其是在那场瘟疫之后。
　　可以说在九道沟村民心里，李大爷就是他们的救命恩人！
　　姓赵的干部说李大爷是杀人犯，就等于指着全体村民的鼻子骂祖宗！
　　最先发难的，是泼辣的张嫂：
　　“你这同志会不会说话？”
　　“无凭无据的，怎能乱冤枉人？！”
　　原本在一旁看热闹的村民纷纷附和：
　　“就是就是，李大爷是好人，我们都能给他作证。”
　　有脾气暴躁的村民，甚至要动手打赵姓干部。
　　幸亏被别人拉住。
　　“别在这打他，警察在呢！”
　　“光天化日的，也会给李大爷添麻烦。”
　　“一会儿咱们几个去村外等，在这瘪犊子回去的路上打他！”
　　“把自行车都给他砸了！”
　　说话的人虽然尽力压低了声音，怎奈庄稼人天生大嗓门，还是被赵干部听得一清二楚。
　　“反了你们这群刁民，还想打我？！”
　　“我是国家干部，看谁敢动我一下试试！”
　　赵干部的话，彻底激怒了在场村民。
　　群情激奋下，纷纷冲了上来。
　　“你特娘的叫谁刁民呢？”
　　“乡亲们一起上，打死这个狗娘养的！”
　　田志刚见此，急的满头大汗：
　　一面是他领导，万万不敢得罪；
　　另一面是从小一起生活的父老乡亲，这要一句话说不好，就会伤众。
　　因此只能小声对李大爷说道：
　　“您老快说句话吧。”
　　“这位是乡长小舅子，真要打了他，吃亏的还是咱们！”
　　李大爷是老红军，一身脾气又臭又硬。
　　若不是顾全大局，他可不管什么乡长小舅子。
　　就是市长他爹，老爷子都照打不误！
　　狠狠的瞪了一眼赵干部后，李大爷对着村民一声冷哼。
　　“都闭嘴，消停的一边待着去！”
　　村民见李大爷发话，立即不再嚷嚷。
　　不过看向赵干部的眼神，更加不善。
　　“瘪犊子，你给…
```

译文节选：

```text
Seeing this, the township cadre surnamed Zhao who had come along grew displeased.

Because he felt he had been slighted.

Cadre Zhao looked Old Master Li up and down with an appraising gaze.

“Why must an old comrade act so mysteriously?!”

“If there’s something to discuss, say it right here!”

“Everything must be subject to the supervision of the masses!”

“There’s nothing that can’t be seen by others, unless... unless you’re connected to this murder case, and you killed the person!”

The moment those words left his mouth, they immediately provoked public outrage.

Old Master Li’s prestige in the village was even higher than Granny Deaf’s.

Especially after that plague.

It could be said that in the hearts of the people of Jiudaogou Village, Old Master Li was their savior!

For the cadre surnamed Zhao to say Old Master Li was a murderer was equivalent to pointing at all the villagers’ …
```

#### 第64章 第64章 逆天改命

- version_id：`225`
- draft_role：`primary`
- model：`gpt_5_5_aicodelink` / `gpt-5.5`

观察：
- 修行规则和对话信息完整。
- `法不传六耳` 直译解释不足，面向英文读者最好通过注释层或自然化处理补足“secret teachings must not reach outsiders”的含义。

原文节选：

```text
在华九难开始讲解之前，灰老六又招来数只两米多长的大老鼠：
　　“劳烦众位兄弟把守四周，任何生灵不得靠近百米范围。”
　　华九难不懂规矩，但灰老六懂：
　　法不传六耳！
　　葛天师一脉传承，若是不小心让外人听去一字一句，都是天大的罪过！
　　大老鼠们朝着华九难恭敬一拜，然后各自分散到周围警戒。
　　华九难教的认真，灰老六学的仔细。
　　不知不觉间已经到了后半夜。
　　华九难得到《抱朴子内篇》时间还短，已经没有什么可教的了。
　　“灰六哥，我记住的都讲完了。”
　　“要不这样，等回去后把书给你，你自己看着学习。”
　　灰老六敬佩华九难为人坦荡的同时，赶忙连连摆手：
　　“小先生，这件事情万万使不得！”
　　“老六我出身卑微、福源浅薄，那等奇物到我手里，只能招来横祸！”
　　“小先生若还肯教我，等你学会了再传授就是！”
　　华九难也不坚持，他忽然想到另一个问题：
　　“灰六哥，我想把道法也传给大计，你看能行么？”
　　华九难的事情，灰老六都会慎重回答。
　　他低头琢磨了一会儿才开口说道：
　　“能不能走上修行这条路，主要看个人的机缘和命数。”
　　“若是刻意为之，反而会适得其反。”
　　“稍有不慎，还会惹来无妄之灾！”
　　华九难点头表示自己明白了，再看向灰老六时，忽然笑出了声。
　　“灰六哥，这么一会儿功夫，你好像变帅了很多！”
　　灰老六秉承了本体特点，本来就长得獐头鼠目、一副猥琐大叔的形象。
　　可学习了正统道法后，气质改变很多。
　　多了几分淡然出尘的气息。
　　对于自己的变化，灰老六早就感觉到了。
　　被华九难调侃，这位灰家家主居然有些不好意思：
　　“这不多亏小先生怜悯，传我正统大道。”
　　“我才能逆天改命，以后修行会顺畅很多！”
　　书中暗表：灰老六说的逆天改命，可没有一点夸张成分。
　　他这一脉受到先天条件限制，从古至今都没有人能位列仙班。
　　尤其是老鼠被定为四害之一，这等于彻底封死了他们修行的道路。
　　别说成仙，修行都难！
　　退一万步讲，即使灰老六运气逆天，修行到了“仙”的境界，充其量也就是野仙。
　　不但进不了庙堂，受不得人间香火，还会被其他“仙…
```

译文节选：

```text
Before Hua Jiunan began explaining, Hui Laoliu summoned several more giant rats over two meters long.

“May I trouble you brothers to guard the surroundings. No living creature is allowed within a hundred meters.”

Hua Jiunan did not understand the rules, but Hui Laoliu did:

The Dharma is not passed to six ears!

For the inheritance of Celestial Master Ge's lineage, if even a single word or sentence were accidentally overheard by an outsider, it would be a grave sin!

The giant rats bowed respectfully to Hua Jiunan, then dispersed to stand guard around the area.

Hua Jiunan taught earnestly, and Hui Laoliu learned carefully.

Before they knew it, it was already the latter half of the night.

Hua Jiunan had only obtained Inner Chapters of Baopuzi not long ago, and there was already nothing more he could teach.

“Brother Hui Liu, I’ve finished explaining everything I remember.”

“How abo…
```

### deepseek

#### 第6章 第6章 冤魂骨

- version_id：`170`
- draft_role：`secondary`
- model：`deepseek_v4_pro` / `deepseek-v4-pro`

观察：
- 动作链完整，但英文里有 `tore simply` 这种不自然搭配。
- DeepSeek 段落保留了 Markdown 双空格换行，导出可读性和格式一致性需要观察。

原文节选：

```text
断头鬼伸出鬼爪简单一撕，吊死鬼舌头被一分为二。
　　断掉的部分，被娃娃几口吃了下去。
　　窗外吊死鬼赶忙趁机逃走。
　　断头鬼也不追赶，开口说道：
　　“我修的是正道，不杀生，便宜你了！”
　　说完之后他猛然觉得脊背发寒，赶忙回头。
　　正看到娃娃不怀好意的盯着自己......
　　此时屋外，各种恶鬼纷纷显形。
　　有老有幼，面目狰狞。
　　众鬼接踵摩肩，挤成一团朝李大爷、聋婆二人扑来。
　　聋婆洒下的香灰，在噼里啪啦的爆响中消耗殆尽。
　　二老虽然拼尽全力，但恶鬼实在太多。
　　况且里面还有很多百年老鬼。
　　李大爷、聋婆背靠着背，一点点退到屋檐下。
　　“三娃，我们挡不住了！”
　　“你带着媳妇快跑！”
　　“记得跑到东山顶老松树下面！”
　　王三从屋顶跳了下来，依然单手高举大印。
　　“娘俺不跑！”
　　“你带着俺媳妇跑吧，俺和李大叔帮你挡着脏东西！”
　　不等聋婆说话，断头鬼抱着娃娃飞了出来。
　　不过此时，断头鬼拎着的脑袋神情呆滞，显然是被娃娃控制住了。
　　群鬼见到极阴子，瞬间凶态毕露，呼啸着就要上他的身。
　　鬼快，这个刚出生的娃娃更快：
　　他咯咯一笑，居然钻进了死去女子的肚子里！
　　女尸瞬间直挺挺的起身，喉咙里发出呼呼的声音。
　　死灰色的双眼环顾四周，流出腥臭的口水！
　　砂石摩擦的声音从女尸口中发出，随后猛地扑向群鬼。
　　惨叫声，撕咬声响彻夜空。
　　聋婆婆惊掉了下巴：
　　“这娃娃这么凶？！”
　　“刚出生就这么厉害，以后得邪乎成啥样？！”
　　出马仙常八爷倒是没有一丝喜色：
　　“哎，再凶也就这一阵儿的事。”
　　“等过会儿胎气彻底散了，也就是个普通娃娃！”
　　事情果然和常八爷说的一样：
　　一刻钟后，还追着群鬼乱咬的女尸忽然倒了下去。
　　小娃娃带着一身腥臭的尸水，呼的一声破腹而出，飞到李大爷怀里。
　　对着他咯咯咯的笑。
　　李大爷满脸无奈，将娃娃紧紧裹在棉衣里。
　　“这孩子究竟是什么怪物......”
　　惊魂未定的群鬼，见此情景再次围了上来。
　　不过有了刚才的事情，明显谨慎很多。
　　那样子说是小心翼翼也不为过。
　　眼见李…
```

译文节选：

```text
The Headless Ghost extended its ghostly claw and tore simply—the Hanged Ghost’s tongue was split in two.
The severed half was devoured by the Baby in a few gulps.
Outside the window, the Hanged Ghost seized the chance to flee.
The Headless Ghost did not give chase, but spoke:
“I cultivate the Righteous Path—I take no life. Count yourself lucky!”
As the words left his mouth, a sudden chill shot down his spine, and he whirled around—
only to see the Baby staring at him with ill intent...

By now, outside the house, all manner of evil ghosts were manifesting.
Some were old, some young, all with twisted, hideous faces.
Jostling and pressing together, the throng of ghosts surged toward Old Master Li and Granny Deaf.
The incense ash Granny Deaf had scattered burst and crackled until it was utterly spent.
Though the two elders fought with everything they had, the evil ghost…
```

#### 第51章 第51章 九字真言

- version_id：`214`
- draft_role：`secondary`
- model：`deepseek_v4_pro` / `deepseek-v4-pro`

观察：
- 术法/口诀段落基本可读。
- 部分宗教术语偏字面，建议抽查九字真言、道教术语是否有固定译名漂移。

原文节选：

```text
从此以后，华九难白天上课学习，回到宿舍后就研究《抱朴子内篇》。
　　此书一共分为二十卷，分别记录了不同内容，比如：
　　形神相离、讲述服药、行气、禁咒诸法；
　　如何辟谷、吞气、隐沦、变化、导引、召神、存思等等内容。
　　其中最广为人知的，就是《登涉卷》中记载的九字真言：
　　“临兵斗者，皆阵列前行。”
　　“凡九字，常当密祝之，无所不辟。要道不烦，此之谓也。”
　　意思是说，常默念这九个字，就可以辟除一切邪恶。
　　东密（日本佛教主要宗派之一，密宗的一种）受到我国道教的影响，使用护咒法。
　　可是在抄录这九个字时，把‘临兵斗者，皆阵列前行。’误抄成‘临兵斗者，皆阵列(裂)在前’，而沿用至今。
　　随着日本动漫的引用，这种错误的九字真言更为国人熟知。
　　这可真够讽刺的！
　　颇有大师在流浪，小丑坐殿堂的意味。
　　此外通过研习《抱朴子内篇》，华九难还学会了风水之术、道家符箓、各种手印法决。
　　若是道人魂魄没有离开，一定会惊叹华九难学习速度之快。
　　这一切仿佛他原本就会，如今只是复习一遍。
　　转眼间又到了周末，陈富亲自开车来接陈大计、华九难二人回家。
　　当然，也会顺路拉上虎娃。
　　一见面，华九难就被陈富的脸色吓了一跳：
　　原本红光满面，如今变成黑里透红！
　　按照书中记载，这是凶煞临头、血光外溢之相！
　　“陈叔叔，家里最近没发生什么事情吧？”
　　陈富边开车边回答：
　　“没有啊，一切都好！”
　　“有老婶子送我的神斧，再加上这块古玉，如今咱百无禁忌！”
　　陈富说完，又把脖子上的挂坠放到嘴边亲了亲。
　　华九难察觉，这颗古玉已经从淡黄向暗红转变。
　　而且散发出的气息更加阴冷。
　　就连一向粗心的陈大计，也察觉到了古玉的变化。
　　“爸，你戴的玩意儿怎么变色了？”
　　“如今暗了吧唧，还不如原来的屎黄色好看！”
　　陈富没好气的瞟了一眼自己儿子：
　　“你小子懂个屁啊！”
　　“‘人养玉三年、玉养人一生’，这说明老子养的好！”
　　陈大计不敢争辩，赶忙陪笑：
　　“行，你是爹，你说的算！”
　　一行人先送虎娃回家，然后一起来到聋婆婆院子。
　　老人家正…
```

译文节选：

```text
From then on, Hua Jiunan attended classes during the day, and after returning to the dormitory, he studied the *Inner Chapters of Baopuzi*.
The book consists of twenty volumes, each recording different contents, such as:
the separation of form and spirit, discourses on taking medicines, practicing qi, and incantations;
methods of fasting, swallowing qi, concealment, transformation, guidance, summoning deities, visualization, and more.
Among them, the most widely known is the Nine-Word Mantra recorded in the "Dengshe Volume":
"Lin, Bing, Dou, Zhe, Jie, Zhen, Lie, Qian, Xing."
"These nine words, constantly and secretly invoked, can ward off all evils. The essential Way is not complicated—this is what it means."
That is, silently reciting these nine words constantly can ward off all evil.
Japanese Shingon Buddhism (one of the major sects of Japanese Buddhism, a form of Esoteric Buddhism), …
```

#### 第69章 第69章 又见尸玉

- version_id：`232`
- draft_role：`secondary`
- model：`deepseek_v4_pro` / `deepseek-v4-pro`

观察：
- 情节信息完整，语气基本到位。
- `The wind whistles, the waters of Yi are cold` 对典故做了字面翻译；是否需要注释层应由读者定位决定。

原文节选：

```text
张顺最终还是选择留下。
　　华九难带着虎娃、陈大计，径直朝着门口走去。
　　看那背影，颇有“风萧萧兮易水寒”的惨烈。
　　半路上，陈大计、虎娃各自捡起半截板砖藏在怀里。
　　陈大计不忘叮嘱：
　　“虎子，一会儿打起来，只能用它砸那帮瘪犊子脑门，不能砸后脑知道么？”
　　“砸后脑会死人的！”
　　虎娃显然很紧张，紧咬着牙说知道了。
　　到了门口，一群人呼啦一下围了上来。
　　为首的一个高个子吊儿郎当的说道：
　　“可以啊，居然还敢出来！”
　　“我们赵老大请你们仨去那边聊聊！”
　　陈大计吐掉嘴里叼的枯树枝，骂骂咧咧说道：
　　“卧槽，去就去，谁怕谁！”
　　“老子也正想和他好好聊聊呢！”
　　众人走了很远，直到过了一处拐角才停下来。
　　赵飞搂着一个女孩，在一帮人簇拥下，似笑非笑的看着华九难三人。
　　“你们三个小B崽子，这次落在老子手里了吧？”
　　陈大计看着气势汹汹的一群人，有些心虚。
　　他轻声对已经哆嗦的虎娃说道：
　　“虎子，你小子怎么做的情报工作？！”
　　“这特么哪是二十多人，怎么说也有五十个！”
　　在他俩说话的时候，华九难一脸冷漠的走到赵飞面前。
　　直到几乎脸贴脸才停下来。
　　这股气势，吓得赵飞搂着的女生连退几步。
　　“赵飞，来单挑！”
　　赵飞先是一愣，随后破口大骂，挥拳朝着华九难鼻子打来。
　　“卧槽！你这是找死！”
　　前文说过，赵飞这家伙膘肥体壮：
　　一米八多身高，二百八十斤的体重。
　　凭借身材优势，在同龄人里打架单挑，他就没输过！
　　华九难虽然也有一米八几，但在赵飞面前，就显得太过单薄。
　　用现代格斗专业术语，他们俩就不是一个重量级的！
　　然而两人单挑的结果，却是华九难完胜！
　　我国古武术，那是无数先辈用生命总结出来的杀人技。
　　华九难勤学苦练十多年，还有一身龙皮加持。
　　用来对付赵飞这种普通人，简直就相当于用大炮打蚊子。
　　轻松写意！
　　甚至可以说纯属浪费！
　　仅仅一个照面，赵飞就被华九难打倒在雪地上，一顿暴踹。
　　当然，华九难出手很注意分寸，并没有朝要命的地方打。
　　赵飞双手抱头，一边惨嚎一边对着自己人大…
```

译文节选：

```text
Zhang Shun ultimately chose to stay.
Hua Jiunan, bringing Huwa and Chen Daji, headed straight for the door.
Watching their retreating figures, there was a tragic solemnity reminiscent of "The wind whistles, the waters of Yi are cold."
On the way, Chen Daji and Huwa each picked up half a brick and hid it inside their clothes.
Chen Daji didn't forget to remind:
"Huzi, when the fight starts, you can only use it to hit those wretched bastards on the forehead, not the back of the head, got it?"
"Hitting the back of the head can kill!"
Huwa was clearly very nervous, gritting his teeth and saying he understood.
At the door, a crowd swarmed around them in an instant.
The leader, a tall guy, said cockily:
"Not bad, you actually dared to come out!"
"Our Boss Zhao wants the three of you to come over there for a chat!"
Chen Daji spat out the dry twig he was chewing and cursed:
"Holy shit, let's go …
```

### rewrite

#### 第7章 第7章 雪尸

- version_id：`171`
- draft_role：`rewrite`
- model：`gpt_5_5_aicodelink` / `gpt-5.5`

观察：
- rewrite 版比普通初稿更像润色后文本，句群衔接较顺。
- `Vengeful Spirit Bone` 与 hard glossary 里的 `vengeful ghost` 不冲突，但同类鬼怪术语需要统一表。

原文节选：

```text
清风堂断头鬼闻言大惊：
　　“冤魂骨？！”
　　“这东西不能吃！”
　　也不怪清风激动，吃了冤魂骨后，会永不超生！
　　魂魄漂泊浪荡在这世间，每时每刻都要承受凌迟之痛。
　　那可真是求生不得、求死不能！
　　在我国漫长的历史中，只有黄巢那个疯子兵败狼虎谷后吃过。
　　所以死后变成厉鬼，带着残魂败将为祸一方千百年。
　　直到惹怒了刘伯温，才被他镇压在首阳碑下面。
　　今夜注定是多事之秋。
　　就在两个老人要吞下冤魂骨的时候，雪山上忽然传来轰鸣声。
　　那声音仿佛闷雷。
　　李大爷开口问道：
　　“难道是雪崩？”
　　聋婆婆摇了摇头：
　　“不是雪崩，你看这些脏东西神情，他们在怕！”
　　“鬼可是不怕雪崩的！”
　　两人说话间，轰鸣声戛然而止。
　　一阵寒意从脚下雪地传来。
　　群鬼吓得紧紧团缩在一起。
　　那样子像极了受惊的鹌鹑。
　　就连麻衣姥姥的轿子，也急忙飘到空中。
　　聋婆婆一声苦笑：
　　“又有大家伙从地底下来了！”
　　“这次就算我俩吃下冤魂骨，也只有被吞的份！”
　　原本极寒的天气，这时能滴水成冰。
　　阴风仿佛都被冻住，不再呼呼咆哮。
　　唯有空中的红月更加娇艳，仿佛随时能流出血来。
　　一个三米多高的身影，从地面缓缓升起。
　　血迹斑斑的铁链，一圈一圈的缠在他身上。
　　铁链的尽头，串着十几只恶鬼。
　　他们骨瘦如柴，极力忍受着痛苦。
　　满眼畏惧的盯着巨大的身影，不敢发出一点声音。
　　四梁之一，断头鬼惊呼出声：
　　“传说是真的！他是雪尸！”
　　闻听此言，女鬼抬着的轿子猛然一震。
　　麻衣姥姥甚至连话都没敢说，就这么消失在原地。
　　连盘在轿子上的常八爷，都被丢在地上。
　　群鬼更是瞬间作鸟兽散，只留下聋婆婆他们面面相觑。
　　雪尸几步走到李大爷身前，灰蒙蒙的眼睛，静静打量着他怀里的婴儿。
　　此刻婴儿已经睡着，小脸泛着红润。
　　看不出任何异常。
　　李大爷倒是想带着孩子躲开，可是根本就动不了。
　　不但是他，其余所有人都动不了：
　　被雪尸不小心踩住的常八爷，只能露出痛苦的表情，发不出任何声音。
　　打量了一会儿，雪尸僵硬的从身上撕下一根铁条…
```

译文节选：

```text
The Decapitated Ghost of Qingfeng Hall was shocked when he heard it.

“Vengeful Spirit Bone?!”

“That thing must not be eaten!”

Qingfeng could hardly be blamed for losing his composure. Once someone ate a Vengeful Spirit Bone, they would never be reborn!

Their soul would drift through this world forever, suffering the agony of death by a thousand cuts every single moment.

That was truly a fate where one could neither live nor die!

In all of China’s long history, only that madman Huang Chao had ever eaten one after his defeat at Wolf-Tiger Valley.

That was why, after death, he turned into a ferocious ghost, leading the remnants of his defeated army to bring disaster to the region for hundreds, even thousands, of years.

Only after he provoked Liu Bowen was he finally suppressed beneath the Shouyang Stele.

Tonight was destined to be a night of endless trouble.

Just as the two old p…
```

#### 第36章 第36章 人皮灯笼

- version_id：`201`
- draft_role：`rewrite`
- model：`gpt_5_5_aicodelink` / `gpt-5.5`

观察：
- 情节与恐怖氛围保留较好。
- 若该段涉及民俗物件/禁忌，建议抽查 annotation 是否缺失。

原文节选：

```text
众所周知，喝多的人都会渴的厉害。
　　不知睡了多久，华九难渴醒了。
　　他强忍宿醉引起的头痛，从上铺下来找水喝。
　　迷迷糊糊摸到暖水瓶，倒在水杯里。
　　一口喝下去，险些没喷出来：
　　呸，怎么会是啤酒！
　　这时的华九难才想起来，昨晚他们用暖水瓶装酒的事情。
　　看着四个空荡荡的床铺，又看了看墙上挂的电子表，华九难心中一惊：
　　“大计、大计快醒醒！”
　　“都三点了，虎娃他们还没回来！”
　　陈大计睡的迷迷糊糊，翻了个身说道：
　　“没回来就没回来呗，可能吃多了拉稀呢。”
　　“要多蹲一会儿！”
　　宿舍里是没有洗手间的。
　　要想方便，得去外面公共厕所。
　　华九难一把掀开陈大计的被子：
　　“什么多蹲一会儿，他们去挖死人骨头还没回来！”
　　陈大计这才惊醒：
　　“卧槽不是吧！”
　　两人匆忙穿上衣服，拿起手电筒，沿着虎娃他们留在雪地上的脚印，朝着后操场跑去。
　　说来奇怪，脚印中途没有任何停留，一直延伸到操场墙根下。
　　显然虎娃四人是跳墙出去了。
　　陈大计不禁纳闷：
　　“怎么？这是怕里面挖不到，去后山上挖骨头了？”
　　华九难经历的多，已经意识到事情不妙。
　　他赶忙爬上墙头，果然见一拍脚印朝着深山里去了。
　　“大计快翻墙出来，我担心虎娃他们出事了！”
　　华九难说完，跳下墙头，沿着脚印追了下去。
　　陈大计极重义气，顾不得害怕，赶忙翻墙跟上。
　　不过他是捂着脸跳下墙头的。
　　显然是前几天脸先着地的事情，给他留下了很深的心理阴影。
　　华九难二人离开之后，地下传来一声幽幽叹息。
　　须发皆白的道人魂魄，从地底飘了出来。
　　跟他一起出现的，还有百十个鬼魂。
　　男女老少都有。
　　不过这些鬼魂和道人一样，没有丝毫凶虐气息，各个面色平和。
　　其中一个拄着拐杖的老鬼说道：
　　“看来要出大事儿喽！”
　　“那会儿刚被人皮灯笼带走四个，这又追过去两个。”
　　“哎，可惜他们年纪轻轻，就做了短命鬼！”
　　眼见道人魂魄望着后山不说话，拄着拐杖的老鬼又开口劝说：
　　“道爷您还是别多管闲事，人皮灯笼凶得很，咱们这些人得罪不起啊！”
　　另一边，心急如焚…
```

译文节选：

```text
As everyone knows, people who drink too much wake up desperately thirsty.

After sleeping for who knew how long, Hua Jiunan was jolted awake by his thirst.

Forcing himself to endure the headache brought on by his hangover, he climbed down from the top bunk to look for water. Still half-asleep, he fumbled his way to the thermos and poured some into a cup.

He took one gulp and nearly sprayed it back out.

Pah! Why the hell was it beer?!

Only then did Hua Jiunan remember that last night they had used the thermos to hold alcohol.

He looked at the four empty beds, then at the digital clock hanging on the wall, and his heart gave a sudden jolt.

“Daji, Daji, wake up!”

“It’s already three! Huwa and the others still haven’t come back!”

Chen Daji, still groggy with sleep, rolled over and muttered,

“So what if they haven’t? Maybe they ate too much and got the runs.”

“Maybe they just need …
```

#### 第70章 第70章 尸气罩顶

- version_id：`233`
- draft_role：`rewrite`
- model：`gpt_5_5_aicodelink` / `gpt-5.5`

观察：
- 对白流畅，但口语梗 `抗造` 没有在 excerpt 中明确落到 `able to take a beating`，属于风格译法而非硬错误。
- rewrite 样本仍需和 hard review 的剩余概念词问题合并看，避免 glossary exact 规则牵着译文走。

原文节选：

```text
华九难用脚把九窍玉踢回给赵飞，带着陈大计、虎娃转身就走：
　　“谁要你的破玩意儿，我又不是打劫的！”
　　“还有这几个人，他们没有骨折，休息半小时就好了！”
　　等远离赵飞这一群人，陈大计轻声问华九难：
　　“老大，赵飞那家伙刚拿出来的，是不是九窍玉？”
　　“可为啥他戴着没事，我爸戴了就会倒霉？”
　　“难道是因为他比我爸胖，所以更抗造？”
　　华九难点头：“那块确实是九窍玉之一，至于为啥赵飞戴着没事，我也不知道。”
　　陈大计忽然想起一个有意思的事，继续问道：
　　“老大，赵飞戴的玉，是塞在哪里的？”
　　华九难被他问笑了：
　　“这块比你爸那块还恶心，是堵着那玩意儿的！”
　　陈大计哈哈大笑：
　　“卧槽！不知道赵飞那瘪犊子，会不会也每天都亲一下！”
　　“想想就觉得恶心！”
　　虎娃不懂什么是九窍玉，也对这些不感兴趣。
　　他感兴趣的是，华九难刚才是怎么让“敌人”不能动的。
　　“九难哥，难道你还会点穴？”
　　“能教教俺不？”
　　他这么一说，也把陈大计的兴趣勾起来了。
　　“老大，我也想学！”
　　华九难苦笑：
　　“我可不会点穴！”
　　“刚刚那叫金针刺穴，治病救人时用的。”
　　“当然，关键时候也能防身。”
　　“哦，是这样啊！”
　　陈大计、虎娃脑补了一下自己拿根针，追着别人扎的画面，顿时没了兴趣。
　　他们又不是东方不败......
　　“那我们不学了！”
　　等三人走到门口，正好遇到来接他们的陈富。
　　在华九难眼里，他额头的黑色更浓了。
　　面相上来说，这叫“黑云压城”，会要命的！
　　不行，得赶快想个办法救他！
　　“陈叔，你最近有没有觉得不舒服？”
　　陈富一边打哈欠一边回答：
　　“也不知道咋滴了，最近吃不好、睡不好的，总觉得心惊肉跳。”
　　就在华九难琢磨怎么帮陈富的时候，陈大计开口问道：
　　“爸，古墓那边咋样了，挖开没有？”
　　陈富无精打采的回答：
　　“具体情况不知道，你们走后我再也没去过，听别人说暂时没挖。”
　　“哦对了，那个小道士去镇上买了好多朱砂黄纸之类的，说是要开坛做法。”
　　“看来古坟里的东西挺邪乎！”
　　半路上…
```

译文节选：

```text
Hua Jiunan kicked the Nine-Orifice Jade back to Zhao Fei with his foot, then turned and walked away with Chen Daji and Huwa.

“Who wants your lousy thing? It’s not like I’m here to rob you!”

“And those guys—none of them have broken bones. Let them rest for half an hour and they’ll be fine!”

Once they were far away from Zhao Fei and his group, Chen Daji lowered his voice and asked Hua Jiunan,

“Boss, that thing Zhao Fei took out just now—was it a Nine-Orifice Jade?”

“But why is he fine wearing it, while my dad gets bad luck as soon as he wears one?”

“Is it because he’s fatter than my dad, so he’s tougher?”

Hua Jiunan nodded. “That piece is indeed one of the Nine-Orifice Jades. As for why Zhao Fei can wear it without anything happening, I don’t know either.”

Chen Daji suddenly thought of something funny and asked again,

“Boss, where exactly was Zhao Fei’s jade plugged?”

Hua Jiunan…
```

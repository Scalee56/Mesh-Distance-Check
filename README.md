# Mesh Distance Check

Add-on per Blender 4.2 o versioni successive. Mostra nella Vista 3D le distanze tra superfici mesh. Le misure tengono conto delle trasformazioni degli oggetti e dei modificatori valutati.

## Installazione

1. [Scarica mesh_distance_check.zip](https://github.com/Scalee56/Mesh-Distance-Check/raw/refs/heads/main/mesh_distance_check.zip).
2. In Blender apri **Modifica → Preferenze → Add-on**, scegli **Installa da disco** dal menu e seleziona lo ZIP.
3. Attiva **Mesh Distance Check**. Nella Vista 3D premi **N** e apri la scheda **Mesh Distance**. Per vedere i risultati, tieni attive le sovrapposizioni della viewport.

Se un aggiornamento precedente ha restituito `cannot import name 'closest_surfaces'`, chiudi e riapri Blender e installa lo ZIP aggiornato.

## Analisi tra più mesh

1. In modalità Oggetto seleziona almeno due mesh con facce oppure attiva **Tutte le mesh visibili**.
2. Premi **Mostra heatmap**. Ogni punto campionato su ciascuna mesh è colorato in base alla superficie più vicina fra le altre mesh dell'analisi. La stessa distanza ha lo stesso colore su tutti i componenti.
3. Premi **Misura distanza minima** per tracciare in giallo una stima del segmento più corto fra tutte le coppie di mesh. La ricerca esamina prima le zone più promettenti e termina quando la distanza può migliorare al massimo di 0,005 mm. Con le unità della scena configurate, la misura viene visualizzata al centesimo di millimetro. Con il sistema unità impostato su Nessuno, resta in BU.

La legenda usa una scala comune che va dal rosso (vicino) al blu (lontano). Con **Fine scala** a zero, usa il minimo e il massimo campionati nell'intero gruppo. Per confrontare analisi diverse, imposta un valore positivo. La scala parte da zero e quel valore corrisponde al blu. Le distanze superiori restano blu. Le zone sicuramente oltre il limite saltano il campionamento dettagliato. In automatico vengono campionate anche le aree più lontane, perché servono a determinare la scala.

La heatmap usa campioni aggiuntivi dentro le facce e interpola i valori sulla superficie. Aumenta **Risoluzione** per mostrare zone di vicinanza più piccole e ricalcola. Il pannello indica il passo di campionamento stimato. Nelle scene dense, l'add-on limita la suddivisione della visualizzazione. La linea gialla usa una ricerca spaziale separata sulle superfici, indipendente dalla risoluzione e dalla scala della heatmap.

## Sonda

In modalità Oggetto premi **Sonda (clic per misurare)** e fai clic sulla superficie di una mesh inclusa nell'analisi. La linea verde va dal punto sotto il cursore al punto più vicino su un'altra mesh del gruppo. Puoi piazzare più sonde in sequenza. Premi **Esc** o il tasto destro per terminare, e **Cancella sonde** per rimuoverle dalla viewport.

In modalità Modifica puoi anche selezionare un vertice e premere **Misura dal vertice selezionato**. Scegli una **Destinazione** oppure lascia il campo vuoto per cercare tra le altre mesh visibili.

Le sovrapposizioni sono istantanee della geometria al momento della misura. Ricalcolale dopo aver spostato o modificato le mesh. **Cancella risultati** rimuove tutte le sovrapposizioni dell'add-on.

## Correzione della distanza minima

In modalità Oggetto seleziona almeno due mesh, imposta **Distanza minima (mm)** (predefinita a **0,30 mm**) e premi **Correggi distanza minima**. La correzione cerca di spostare localmente i vertici delle mesh selezionate, distribuendo lo spostamento sui lati vicini. Usa la geometria risultante dai modificatori e la scala unità della scena per convertire i millimetri.

Se la verifica riesce, troverai selezionate le copie con suffisso **Distanza**. Includono i modificatori applicati alla geometria. Gli originali restano nella scena, nascosti nella vista corrente. Puoi mostrarli di nuovo dall'Outliner oppure annullare l'operazione con **Ctrl+Z**.

Il controllo di **1 mm** riguarda le facce deformate e le relative pareti opposte. Fori o difetti lontani dalla correzione sono ammessi. Se la mesh è aperta o non manifold, ogni sonda di controllo sulla zona deformata deve trovare una parete opposta misurabile. Una superficie singola senza spessore viene quindi rifiutata quando la correzione dovrebbe deformarla.

Il controllo combina la distanza fra facce contrapposte con sonde campionate. Può respingere alcuni dettagli acuti e non sostituisce una verifica dello spessore per la produzione. Se rileva spessore insufficiente o non verificabile, una nuova intersezione nella zona modificata o distanza finale insufficiente, mostra un avviso e scarta le copie. Le mesh già a contatto o intersecate devono essere leggermente separate prima della correzione.


## Prova rapida

Crea tre cubi standard larghi 2 unità con centri a X = −4, 0 e 3. Selezionali tutti. Il minimo globale atteso è 1 unità Blender, tra il cubo centrale e quello a destra. La heatmap deve coprire tutti e tre i cubi con la stessa scala.

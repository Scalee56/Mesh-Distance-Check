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

## Zone critiche e Vertex Groups

1. Imposta **Fine scala** e premi **Mostra heatmap** in modalità Oggetto.
2. Con **Seleziona entrando in Modifica** attivo, entra in modalità Modifica sui componenti analizzati. Puoi anche premere **Seleziona zone critiche** per entrare in Modifica o rifare la selezione.
3. Nel pannello **Vertex Groups**, scegli o crea un gruppo e premi **Assign**. Per assegnare gruppi diversi, usa il gruppo del componente attivo.

La selezione segue la fascia dal rosso al rosso-magenta, il primo 20% della scala visibile. Se la nuova scala supera i dati campionati, il pannello chiede di ricalcolare la heatmap. Se una zona rossa cade tutta all’interno di una faccia, non vengono selezionati vertici esterni alla fascia. Ricalcola la heatmap dopo aver modificato la geometria. I modificatori che cambiano la corrispondenza con i vertici originali possono impedire la selezione sul relativo oggetto.

## Sonda

In modalità Oggetto premi **Sonda (clic per misurare)** e fai clic sulla superficie di una mesh inclusa nell'analisi. La linea verde va dal punto sotto il cursore al punto più vicino su un'altra mesh del gruppo. Puoi piazzare più sonde in sequenza. Premi **Esc** o il tasto destro per terminare, e **Cancella sonde** per rimuoverle dalla viewport.

In modalità Modifica puoi anche selezionare un vertice e premere **Misura dal vertice selezionato**. Scegli una **Destinazione** oppure lascia il campo vuoto per cercare tra le altre mesh visibili.

Le sovrapposizioni sono istantanee della geometria al momento della misura. Ricalcolale dopo aver spostato o modificato le mesh. **Cancella risultati** rimuove tutte le sovrapposizioni dell'add-on.

## Correzione della distanza minima

In modalità Oggetto seleziona almeno due mesh, imposta **Distanza minima (mm)** (predefinita a **0,30 mm**) e premi **Correggi distanza minima**. Sulle mesh dense, la correzione calcola un primo spostamento su una geometria molto semplificata. Poi trasferisce lo spostamento alle copie con la topologia originale e rifinisce le zone ancora sotto soglia. La barra di stato indica la fase corrente. Premi **Esc** per interrompere e scartare i dati provvisori. Usa la geometria risultante dai modificatori e la scala unità della scena per convertire i millimetri.

Per vedere quali zone richiedono una correzione, imposta **Fine scala** allo stesso valore di **Distanza minima (mm)** e ricalcola la heatmap. Con la scala automatica il rosso può indicare la distanza più piccola della selezione anche se è già sopra soglia.

Se la verifica riesce, troverai selezionate le copie con suffisso **Distanza**. Includono i modificatori applicati alla geometria. Gli originali restano nella scena, nascosti nella vista corrente. Puoi mostrarli di nuovo dall'Outliner oppure annullare l'operazione con **Ctrl+Z**.

Il controllo di **1 mm** riguarda le facce deformate e le relative pareti opposte. Fori o difetti lontani dalla correzione sono ammessi. Se la ricerca lungo la normale fallisce su una mesh aperta, vengono controllate anche direzioni oblique.

La verifica finale controlla la distanza minima sulla geometria completa. **Risoluzione** regola anche l’intensità del campionamento dello spessore sulle facce modificate, oltre alla heatmap. Il controllo combina la distanza fra facce contrapposte con sonde campionate. La validazione si basa sulla geometria finale e consente variazioni di orientamento delle facce. Se lo spessore è inferiore a 1 mm o non è verificabile, le copie vengono comunque create e il pannello mostra un avviso per ciascun componente coinvolto. Se ci sono spostamenti ma la verifica geometrica fallisce, le copie vengono mostrate con il suffisso **Correzione parziale**. Il pannello indica le verifiche fallite. I contatti iniziali possono ancora impedire al calcolo di produrre uno spostamento.


## Prova rapida

Crea tre cubi standard larghi 2 unità con centri a X = −4, 0 e 3. Selezionali tutti. Il minimo globale atteso è 1 unità Blender, tra il cubo centrale e quello a destra. La heatmap deve coprire tutti e tre i cubi con la stessa scala.

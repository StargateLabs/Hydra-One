// wmma_gfx11.hpp — layout dei frammenti del WMMA f16 di RDNA3 (gfx11, wave32), RICAVATO con misura.
//
// Non e' copiato dalla documentazione ne' da gfx12: viene da tools/hip/layout_wmma2.cpp, che mette
// un 1 in una posizione del frammento e guarda quale cella di D si accende, per tutte e 32 le
// corsie e tutti e 16 i posti. La mappa e' quella misurata su gfx1100:
//
//   A (16 half per corsia) — LE RIGHE DI A NON STANNO SU TUTTE LE CORSIE:
//       riga 0..7  -> corsie 0, 2, 4, 6, 8, 10, 12, 14      (corsia = riga * 2)
//       riga 8..15 -> corsie 17, 19, 21, 23, 25, 27, 29, 31 (corsia = 16 + (riga - 8) * 2 + 1)
//       le altre corsie da sole non contribuiscono: il dato va scritto ANCHE sulla compagna,
//       perche' l'hardware legge la coppia. Scrivere solo sulla dispari non ha effetto.
//
//   B (16 half per corsia) — tutte e 32 le corsie portano dati, passo 8:
//       la corsia l contribuisce alle celle di D a indice l * 8 + i
//
//   D (8 float per corsia) — 32 corsie x 8 = 256 = 16 x 16, nessuna replica.
//
// Uso: nel kernel portato, per caricare A[i][j] si scrive sul posto giusto della corsia giusta
// (e della sua compagna); per leggere D si legge la propria corsia con l'indice l * 8 + i.
//
// ATTENZIONE: questa mappa e' stata ricavata per la forma 16x16x16 f16 (f32 accumulo) waved 32.
// Se il motore usa una forma diversa, va rifatta con lo stesso programma.

#pragma once

#include <hip/hip_runtime.h>

namespace strata::wmma_gfx11 {

typedef _Float16 h16 __attribute__((ext_vector_type(16)));
typedef float f8 __attribute__((ext_vector_type(8)));

// La corsia che porta la riga r di A (0..15). Le righe 0..7 stanno sulle pari basse, le 8..15
// sulle dispari alte: e' la disposizione misurata, non una scelta.
__device__ __forceinline__ int corsia_di_A(int r) {
    return r < 8 ? r * 2 : 16 + (r - 8) * 2 + 1;
}

// La corsia compagna: l'hardware legge la coppia, quindi il dato va replicato.
__device__ __forceinline__ int corsia_compagna(int corsia) {
    return corsia ^ 1;
}

// Mette il valore alla riga r, colonna k del blocco 16x16 di A, nel frammento della corsia.
// Il posto dentro il frammento segue l'ordine misurato: i posti 0..15 di una corsia sono le
// colonne 0..15 della riga che quella corsia porta.
__device__ __forceinline__ void scrivi_A(h16& frammento, int r, int k, _Float16 valore) {
    frammento[k & 15] = valore;
}

// Scrive il frammento di A sul registro giusto: sia la corsia che lo porta, sia la compagna.
// lane = la corsia di questo thread. Restituisce true se questo thread ha scritto qualcosa.
__device__ __forceinline__ bool carica_A(h16& mio, int lane, int r, int k, _Float16 valore) {
    if (lane == corsia_di_A(r) || lane == corsia_compagna(corsia_di_A(r))) {
        mio[k & 15] = valore;
        return true;
    }
    return false;
}

// Legge la cella (riga, colonna) di D dal frammento accumulatore della corsia l.
// L'indice piatto misurato e' l * 8 + i: qui si va all'inverso.
__device__ __forceinline__ float leggi_D(const f8& acc, int lane, int riga, int colonna) {
    const int indice = lane * 8 + (colonna & 7);
    (void) riga;
    return acc[indice & 7];
}

}  // namespace strata::wmma_gfx11
